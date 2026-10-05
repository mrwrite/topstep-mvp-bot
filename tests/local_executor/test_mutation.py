from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests
from sqlalchemy.exc import OperationalError

from local_executor.journal import LocalJournal
from local_executor.journal_models import (
    Acknowledgement,
    AccountBinding,
    Installation,
    MarketInput,
    OrderIntent,
    PolicyVersion,
    ProposedIntent,
    ProviderOrder,
    ReconciliationLock,
    ReconciliationRun,
    RiskDecision,
    StrategyDecision,
    SubmissionAttempt,
)
from local_executor.mutation import (
    MutationAuthorization,
    MutationPipeline,
    MutationPipelineError,
    MutationPreflight,
    MutationRequest,
)
from local_executor.rate_budget import DurableRateLimiter
from local_executor.reconciliation import ReconciliationError, ReconciliationService
from local_executor.topstep_client import LocalTopstepClient


class FakeResponse:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CleanReconciler:
    def __init__(self, account_id=7):
        self.account_id = account_id
        self.calls = []

    def reconcile_before_mutation(self, request):
        self.calls.append(request)
        return MutationPreflight(
            exact_account_id=self.account_id,
            provider_available=True,
            reconciliation_clean=True,
            local_outstanding_clean=True,
            market_fresh=True,
            clock_healthy=True,
            rate_budget_available=True,
            provider_state_hash="provider-state-hash",
        )


def success(**fields):
    return FakeResponse({"success": True, "errorCode": 0, **fields})


def provider_order(tag="tb-fixture-unique", *, order_id=91, account_id=7, contract=None):
    return {
        "id": order_id, "accountId": account_id,
        "contractId": contract or "CON.F.US.MES.Z26",
        "creationTimestamp": "2026-10-03T15:00:00+00:00",
        "status": 1, "type": 2, "side": 0, "size": 1, "customTag": tag,
    }


def provider_trade(*, account_id=7, order_id=91):
    return {
        "id": 401, "accountId": account_id, "orderId": order_id,
        "contractId": "CON.F.US.MES.Z26", "side": 0, "size": 1,
        "price": 5000.25, "profitAndLoss": None,
        "creationTimestamp": "2026-10-03T15:00:01+00:00", "voided": False,
    }


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "mutation.db", secure_permissions=False)
    yield value
    value.close()


def seed(journal):
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    with journal.session_factory.begin() as session:
        installation = Installation(software_version="fixture", lifecycle_state="practice_armed")
        session.add(installation)
        session.flush()
        binding = AccountBinding(
            installation_id=installation.id,
            credential_generation=1,
            provider_account_id="7",
            provider_account_hash="hash-7",
            account_attestation="practice",
            is_active=True,
        )
        policy = PolicyVersion(
            installation_id=installation.id, version=1, checksum="policy",
            policy={"quantity": 1}, is_active=True,
        )
        market = MarketInput(
            installation_id=installation.id, input_identity="market-input",
            contract_id="CON.F.US.MES.Z26", window_start=now - timedelta(minutes=5),
            window_end=now, payload_hash="market-hash",
        )
        session.add_all([binding, policy, market])
        session.flush()
        decision = StrategyDecision(
            installation_id=installation.id, market_input_id=market.id,
            strategy_version="strategy-v1", configuration_hash="config-v1",
            decision="BUY", rationale="fixture",
        )
        session.add(decision)
        session.flush()
        proposal = ProposedIntent(
            installation_id=installation.id, strategy_decision_id=decision.id,
            account_id="7", instrument=market.contract_id, side="BUY", quantity=1,
            order_type="market",
        )
        session.add(proposal)
        session.flush()
        risk = RiskDecision(
            installation_id=installation.id, proposed_intent_id=proposal.id,
            policy_version_id=policy.id, allowed=True,
            classifications=[], input_snapshot={"safe": True},
        )
        session.add(risk)
        session.flush()
        return installation.id, binding.id, decision.id, policy.id, risk.id


def make_request(ids, **changes):
    installation_id, binding_id, decision_id, policy_id, risk_id = ids
    values = dict(
        action="place", installation_id=installation_id,
        account_binding_id=binding_id, account_id=7,
        strategy_decision_id=decision_id, policy_version_id=policy_id,
        risk_decision_id=risk_id, contract_id="CON.F.US.MES.Z26",
        side="BUY", order_type="market", quantity=1, custom_tag="tb-fixture-unique",
    )
    values.update(changes)
    return MutationRequest(**values)


def auth(now, **changes):
    values = dict(
        exact_account_id=7, lifecycle_state="practice_armed",
        expires_at=now + timedelta(minutes=1), reconciliation_clean=True,
        market_fresh=True, clock_healthy=True,
    )
    values.update(changes)
    return MutationAuthorization(**values)


def pipeline(journal, http, reconciler=None, *, now=None, hook=None):
    clock = (now if callable(now) else
             lambda: now or datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc))
    limiter = DurableRateLimiter(journal.session_factory, clock=clock)
    client = LocalTopstepClient(limiter, http_session=http, read_retries=2)
    return MutationPipeline(
        journal.session_factory, client, reconciler or CleanReconciler(),
        clock=clock, failure_hook=hook,
    )


def test_accepted_place_commits_each_boundary_and_calls_provider_once(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({"success": True, "errorCode": 0, "orderId": 91}))
    reconciler = CleanReconciler()
    outcome = pipeline(journal, http, reconciler, now=now).execute(
        "token", make_request(ids), auth(now)
    )
    assert outcome.classification == "accepted"
    assert outcome.provider_order_id == 91 and outcome.ambiguous is False
    assert len(http.calls) == 1 and len(reconciler.calls) == 1
    payload = http.calls[0][1]["json"]
    assert payload["size"] == 1 and payload["customTag"] == "tb-fixture-unique"
    assert payload["type"] == 2 and payload["side"] == 0
    with journal.session_factory() as session:
        intent = session.query(OrderIntent).one()
        attempt = session.query(SubmissionAttempt).one()
        ack = session.query(Acknowledgement).one()
        assert intent.state == "accepted" and intent.request_hash != "legacy"
        assert attempt.state == "accepted" and ack.provider_order_id == "91"


@pytest.mark.parametrize(
    ("action", "path", "changes"),
    [
        ("cancel", "/api/Order/cancel", {"target_provider_id": 91, "order_type": "cancel"}),
        ("modify", "/api/Order/modify", {"target_provider_id": 91, "order_type": "limit",
                                          "limit_price": "5000.25"}),
        ("close", "/api/Position/closeContract", {"order_type": "market"}),
        ("partial_close", "/api/Position/partialCloseContract", {"order_type": "market"}),
    ],
)
def test_all_mutations_use_same_single_attempt_boundary(journal, action, path, changes):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({"success": True, "errorCode": 0}))
    outcome = pipeline(journal, http, now=now).execute(
        "token", make_request(ids, action=action, custom_tag=f"tb-{action}", **changes), auth(now)
    )
    assert outcome.classification == "accepted"
    assert http.calls[0][0].endswith(path)
    with journal.session_factory() as session:
        assert session.query(OrderIntent).one().action == action
        assert session.query(SubmissionAttempt).count() == 1
        assert session.query(Acknowledgement).count() == 1


@pytest.mark.parametrize("code,classification", [(2, "rejected"), (6, "pending"), (7, "unknown")])
def test_place_provider_classifications_are_typed(journal, code, classification):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({"success": False, "errorCode": code, "orderId": 91}))
    outcome = pipeline(journal, http, now=now).execute(
        "token", make_request(ids), auth(now)
    )
    assert outcome.classification == classification
    with journal.session_factory() as session:
        lock = session.query(ReconciliationLock).one_or_none()
        assert (lock is not None and lock.active) is (classification in {"pending", "unknown"})


def test_rate_limit_is_durable_terminal_outcome_without_retry(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({}, status=429, headers={"Retry-After": "45"}))
    outcome = pipeline(journal, http, now=now).execute(
        "token", make_request(ids), auth(now)
    )
    assert outcome.classification == "rate_limited" and len(http.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [requests.Timeout("timeout"), requests.ConnectionError("lost"),
     FakeResponse(ValueError("bad json"))],
)
def test_ambiguous_transport_and_malformed_outcomes_lock_without_retry(journal, failure):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(failure)
    with pytest.raises(MutationPipelineError):
        pipeline(journal, http, now=now).execute("token", make_request(ids), auth(now))
    assert len(http.calls) == 1
    with journal.session_factory() as session:
        assert session.query(OrderIntent).one().state == "ambiguous"
        assert session.query(SubmissionAttempt).one().state == "ambiguous"
        assert session.query(Acknowledgement).count() == 0
        assert session.query(ReconciliationLock).one().active is True


def test_interruption_boundaries_preserve_recoverable_state(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({"success": True, "errorCode": 0, "orderId": 91}))

    def crash(stage):
        if stage == "after_attempt_commit":
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        pipeline(journal, http, now=now, hook=crash).execute(
            "token", make_request(ids), auth(now)
        )
    assert http.calls == []
    with journal.session_factory() as session:
        assert session.query(OrderIntent).count() == 1
        assert session.query(SubmissionAttempt).count() == 1
        assert session.query(Acknowledgement).count() == 0


def test_lost_acknowledgement_never_causes_a_second_call(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({"success": True, "errorCode": 0, "orderId": 91}))

    def crash(stage):
        if stage == "before_ack_commit":
            raise RuntimeError("simulated-lost-ack")

    with pytest.raises(RuntimeError, match="simulated-lost-ack"):
        pipeline(journal, http, now=now, hook=crash).execute(
            "token", make_request(ids), auth(now)
        )
    assert len(http.calls) == 1
    with journal.session_factory() as session:
        assert session.query(SubmissionAttempt).one().state == "boundary_committed"
        assert session.query(Acknowledgement).count() == 0


def test_duplicate_tag_kill_stale_authorization_and_account_switch_fail_closed(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    first_http = FakeHttp(FakeResponse({"success": False, "errorCode": 2}))
    pipeline(journal, first_http, now=now).execute("token", make_request(ids), auth(now))

    with pytest.raises(MutationPipelineError, match="duplicate_custom_tag"):
        pipeline(journal, FakeHttp(), now=now).execute("token", make_request(ids), auth(now))
    with pytest.raises(MutationPipelineError, match="active_kill"):
        pipeline(journal, FakeHttp(), now=now).execute(
            "token", make_request(ids, custom_tag="tb-kill"),
            auth(now, active_kills=("manual",)),
        )
    with pytest.raises(MutationPipelineError, match="mutation_authorization_stale"):
        pipeline(journal, FakeHttp(), now=now).execute(
            "token", make_request(ids, custom_tag="tb-stale"),
            auth(now, expires_at=now),
        )
    with pytest.raises(MutationPipelineError, match="preflight_account_switch_detected"):
        pipeline(journal, FakeHttp(), CleanReconciler(account_id=8), now=now).execute(
            "token", make_request(ids, custom_tag="tb-switch"), auth(now),
        )


def test_authoritative_reconciliation_links_one_exact_match_without_resubmission(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    mutation_http = FakeHttp(FakeResponse({"success": False, "errorCode": 6, "orderId": 91}))
    pending = pipeline(journal, mutation_http, now=now).execute(
        "token", make_request(ids), auth(now)
    )
    read_http = FakeHttp(
        success(accounts=[{"id": 7, "canTrade": True, "isVisible": True}]),
        success(orders=[provider_order()]), success(trades=[provider_trade()]),
        success(positions=[]),
    )
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now),
        http_session=read_http, read_retries=0,
    )
    outcome = ReconciliationService(
        journal.session_factory, client, "token", clock=lambda: now + timedelta(seconds=5)
    ).reconcile_intent(pending.intent_id)
    assert outcome.authoritative and outcome.matched_provider_order_id == 91
    assert len(read_http.calls) == 4 and len(mutation_http.calls) == 1
    with journal.session_factory() as session:
        assert session.query(OrderIntent).one().state == "reconciled"
        assert session.query(SubmissionAttempt).one().state == "reconciled"
        assert session.query(ReconciliationLock).one().active is False
        assert session.query(ProviderOrder).one().intent_id == pending.intent_id


@pytest.mark.parametrize(
    ("orders", "trades", "classification"),
    [
        ([], [], "zero_matches"),
        ([provider_order(order_id=91), provider_order(order_id=92)], [], "multiple_matches"),
        ([provider_order()], [provider_trade(account_id=8)], "inconsistent_provider_state"),
    ],
)
def test_zero_multiple_and_drift_keep_reconciliation_lock(
    journal, orders, trades, classification
):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    pending = pipeline(
        journal, FakeHttp(FakeResponse({"success": False, "errorCode": 6})), now=now
    ).execute("token", make_request(ids), auth(now))
    read_http = FakeHttp(
        success(accounts=[{"id": 7, "canTrade": True, "isVisible": True}]),
        success(orders=orders), success(trades=trades), success(positions=[]),
    )
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now),
        http_session=read_http, read_retries=0,
    )
    outcome = ReconciliationService(
        journal.session_factory, client, "token", clock=lambda: now + timedelta(seconds=5)
    ).reconcile_intent(pending.intent_id)
    assert outcome.classification == classification
    assert not outcome.authoritative and outcome.lock_active


def test_startup_recovery_distinguishes_unattempted_and_ambiguous(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)

    def stop_after_intent(stage):
        if stage == "after_intent_commit":
            raise RuntimeError("stop-before-attempt")

    with pytest.raises(RuntimeError, match="stop-before-attempt"):
        pipeline(journal, FakeHttp(), now=now, hook=stop_after_intent).execute(
            "token", make_request(ids, custom_tag="tb-unattempted"), auth(now)
        )

    def stop_before_ack(stage):
        if stage == "before_ack_commit":
            raise RuntimeError("lost-ack")

    with pytest.raises(RuntimeError, match="lost-ack"):
        pipeline(
            journal, FakeHttp(success(orderId=92)), now=now, hook=stop_before_ack
        ).execute("token", make_request(ids, custom_tag="tb-ambiguous"), auth(now))

    read_http = FakeHttp(
        success(accounts=[{"id": 7, "canTrade": True, "isVisible": True}]),
        success(orders=[provider_order(tag="tb-ambiguous", order_id=92)]),
        success(trades=[]), success(positions=[]),
    )
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now),
        http_session=read_http, read_retries=0,
    )
    recovered = ReconciliationService(
        journal.session_factory, client, "token", clock=lambda: now + timedelta(seconds=30)
    ).recover_startup()
    assert len(recovered["unattempted"]) == 1
    assert len(recovered["reconciled"]) == 1
    assert recovered["locked"] == ()


def test_periodic_checkpoints_and_operator_resolution_do_not_fabricate_facts(journal):
    ids = seed(journal)
    binding_id = ids[1]
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now),
        http_session=FakeHttp(), read_retries=0,
    )
    service = ReconciliationService(journal.session_factory, client, "token", clock=lambda: now)
    outcome = service.reconcile_account_periodic(binding_id)
    assert outcome.classification == "no_nonterminal_work"
    with journal.session_factory.begin() as session:
        session.add(ReconciliationLock(
            account_binding_id=binding_id, active=True, reason="fixture", acquired_at=now
        ))
    evidence_hash = "a" * 64
    service.record_operator_resolution(
        binding_id, classification="verified_no_order", evidence_hash=evidence_hash,
        direct_provider_verified=True,
    )
    with journal.session_factory() as session:
        lock = session.query(ReconciliationLock).one()
        assert lock.active is False and lock.resolution_evidence["evidence_hash"] == evidence_hash
        assert session.query(Acknowledgement).count() == 0
        assert session.query(ProviderOrder).count() == 0
        run = session.query(ReconciliationRun).one()
        assert run.checkpoints["local_ledger_at"] == now.isoformat()


def test_provider_outage_and_clock_change_fail_closed_before_mutation(journal):
    ids = seed(journal)
    now = [datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)]
    outage_http = FakeHttp(requests.ConnectionError("offline"))
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now[0]),
        http_session=outage_http, read_retries=0,
    )
    service = ReconciliationService(
        journal.session_factory, client, "token", clock=lambda: now[0]
    )
    request = make_request(ids)
    report = service.reconcile_before_mutation(request)
    assert not report.provider_available and not report.reconciliation_clean
    with journal.session_factory() as session:
        assert session.query(ReconciliationLock).one().active is True

    # A clock jump after intent persistence expires authorization before the
    # attempt boundary, so provider I/O remains impossible.
    other_ids = ids
    http = FakeHttp()

    def jump(stage):
        if stage == "after_intent_commit":
            now[0] += timedelta(minutes=2)

    with pytest.raises(MutationPipelineError, match="mutation_authorization_stale"):
        pipeline(
            journal, http, CleanReconciler(), now=lambda: now[0], hook=jump
        ).execute(
            "token", make_request(other_ids, custom_tag="tb-clock-jump"),
            auth(now[0]),
        )
    assert http.calls == []


def test_real_reconciliation_runs_immediately_before_provider_mutation(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(
        success(accounts=[{"id": 7, "canTrade": True, "isVisible": True}]),
        success(orders=[]), success(trades=[]), success(positions=[]),
        success(orderId=91),
    )
    client = LocalTopstepClient(
        DurableRateLimiter(journal.session_factory, clock=lambda: now),
        http_session=http, read_retries=0,
    )
    reconciler = ReconciliationService(
        journal.session_factory, client, "token", clock=lambda: now
    )
    result = MutationPipeline(
        journal.session_factory, client, reconciler, clock=lambda: now
    ).execute("token", make_request(ids), auth(now))
    assert result.classification == "accepted"
    assert [call[0].split(".com")[-1] for call in http.calls] == [
        "/api/Account/search", "/api/Order/searchOpen", "/api/Trade/search",
        "/api/Position/searchOpen", "/api/Order/place",
    ]


@pytest.mark.parametrize("stage", ["after_provider_response", "after_ack_commit"])
def test_response_and_commit_failure_injection_never_repeats_network_call(journal, stage):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(success(orderId=91))

    def stop(current):
        if current == stage:
            raise RuntimeError(stage)

    with pytest.raises(RuntimeError, match=stage):
        pipeline(journal, http, now=now, hook=stop).execute(
            "token", make_request(ids), auth(now)
        )
    assert len(http.calls) == 1
    with journal.session_factory() as session:
        attempt = session.query(SubmissionAttempt).one()
        if stage == "after_provider_response":
            assert session.query(Acknowledgement).count() == 0
            assert attempt.state == "boundary_committed"
        else:
            assert session.query(Acknowledgement).count() == 1
            assert attempt.state == "accepted"


def test_database_writer_lock_stops_before_provider_call(journal):
    ids = seed(journal)
    now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
    http = FakeHttp(success(orderId=91))
    blocker = journal.engine.connect()
    try:
        blocker.exec_driver_sql("BEGIN IMMEDIATE")
        blocker.exec_driver_sql("PRAGMA busy_timeout=20")
        with pytest.raises(OperationalError):
            pipeline(journal, http, now=now).execute(
                "token", make_request(ids), auth(now)
            )
        assert http.calls == []
    finally:
        blocker.rollback()
        blocker.close()
