from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .journal_models import (
    Acknowledgement,
    AccountBinding,
    OrderIntent,
    PolicyVersion,
    ReconciliationLock,
    RiskDecision,
    StrategyDecision,
    SubmissionAttempt,
)
from .topstep_client import ORDER_TYPES, LocalProviderError, LocalTopstepClient, MutationResult


class MutationPipelineError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


@dataclass(frozen=True)
class MutationRequest:
    action: str
    installation_id: str
    account_binding_id: str
    account_id: int
    strategy_decision_id: str
    policy_version_id: str
    risk_decision_id: str
    contract_id: str
    side: str
    order_type: str
    quantity: int = 1
    custom_tag: str = ""
    target_provider_id: int | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    trail_price: str | None = None
    origin: str = "personal_device"


@dataclass(frozen=True)
class MutationAuthorization:
    exact_account_id: int
    lifecycle_state: str
    expires_at: datetime
    reconciliation_clean: bool
    market_fresh: bool
    clock_healthy: bool
    active_kills: tuple[str, ...] = ()
    allow_risk_reducing_during_kill: bool = False


@dataclass(frozen=True)
class MutationPreflight:
    exact_account_id: int
    provider_available: bool
    reconciliation_clean: bool
    local_outstanding_clean: bool
    market_fresh: bool
    clock_healthy: bool
    rate_budget_available: bool
    provider_state_hash: str


class PreMutationReconciler(Protocol):
    def reconcile_before_mutation(self, request: MutationRequest) -> MutationPreflight: ...


@dataclass(frozen=True)
class MutationOutcome:
    intent_id: str
    attempt_id: str
    classification: str
    provider_order_id: int | None
    ambiguous: bool


def stable_custom_tag() -> str:
    return f"tb-{uuid4().hex[:28]}"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _canonical_request(request: MutationRequest) -> dict[str, object]:
    values = asdict(request)
    return {key: value for key, value in values.items() if key not in {"installation_id"}}


def request_hash(request: MutationRequest) -> str:
    return sha256(json.dumps(
        _canonical_request(request), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()


class MutationPipeline:
    """Durable single-attempt provider mutation boundary."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: LocalTopstepClient,
        reconciler: PreMutationReconciler,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        failure_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._client = client
        self._reconciler = reconciler
        self._clock = clock
        self._failure_hook = failure_hook or (lambda _stage: None)

    def execute(
        self,
        token: str,
        request: MutationRequest,
        authorization: MutationAuthorization,
    ) -> MutationOutcome:
        request = self._normalize(request)
        self._authorize(request, authorization)
        intent_id = self._commit_intent(request, authorization)
        self._failure_hook("after_intent_commit")

        preflight = self._reconciler.reconcile_before_mutation(request)
        self._assert_preflight(request, authorization, preflight)
        self._authorize(request, authorization)
        attempt_id = self._commit_attempt(intent_id)
        self._failure_hook("after_attempt_commit")

        try:
            result = self._call_once(token, request)
        except LocalProviderError as exc:
            self._mark_ambiguous(intent_id, attempt_id, exc.classification)
            raise MutationPipelineError(exc.classification) from None
        except BaseException:
            # A process interruption after the attempt boundary is intentionally left
            # without acknowledgement; startup recovery will classify it ambiguous.
            raise

        self._failure_hook("after_provider_response")
        ambiguous = result.classification in {"pending", "unknown"}
        if ambiguous:
            self._record_acknowledgement(intent_id, attempt_id, result, state="ambiguous")
            self._acquire_lock(request.account_binding_id, result.classification)
        else:
            state = "accepted" if result.classification == "accepted" else "terminal"
            self._record_acknowledgement(intent_id, attempt_id, result, state=state)
        self._failure_hook("after_ack_commit")
        return MutationOutcome(
            intent_id=intent_id,
            attempt_id=attempt_id,
            classification=result.classification,
            provider_order_id=result.provider_order_id,
            ambiguous=ambiguous,
        )

    @staticmethod
    def _normalize(request: MutationRequest) -> MutationRequest:
        if request.action not in {"place", "cancel", "modify", "close", "partial_close"}:
            raise MutationPipelineError("unsupported_mutation_action")
        if request.quantity != 1:
            raise MutationPipelineError("quantity_must_equal_one")
        if request.origin != "personal_device":
            raise MutationPipelineError("remote_mutation_origin_prohibited")
        if request.side not in {"BUY", "SELL"}:
            raise MutationPipelineError("unsupported_order_side")
        if request.action in {"cancel", "modify"} and request.target_provider_id is None:
            raise MutationPipelineError("target_provider_order_required")
        if request.action == "place" and request.order_type not in ORDER_TYPES:
            raise MutationPipelineError("unsupported_order_type")
        if request.action == "place" and request.order_type == "trailing_stop" \
                and request.trail_price is None:
            raise MutationPipelineError("trailing_stop_price_required")
        if request.action == "place" and not request.custom_tag:
            request = MutationRequest(**{**asdict(request), "custom_tag": stable_custom_tag()})
        if not request.custom_tag or len(request.custom_tag) > 64:
            raise MutationPipelineError("invalid_custom_tag")
        return request

    def _authorize(
        self, request: MutationRequest, authorization: MutationAuthorization
    ) -> None:
        now = _aware(self._clock())
        if request.account_id != authorization.exact_account_id:
            raise MutationPipelineError("exact_account_mismatch")
        if _aware(authorization.expires_at) <= now:
            raise MutationPipelineError("mutation_authorization_stale")
        if authorization.lifecycle_state not in {"practice_armed", "combine_armed", "running"}:
            raise MutationPipelineError("lifecycle_not_armed")
        if not authorization.reconciliation_clean:
            raise MutationPipelineError("reconciliation_not_clean")
        if not authorization.market_fresh:
            raise MutationPipelineError("market_data_stale")
        if not authorization.clock_healthy:
            raise MutationPipelineError("clock_unhealthy")
        if authorization.active_kills:
            risk_reducing = request.action in {"cancel", "close", "partial_close"}
            if not (risk_reducing and authorization.allow_risk_reducing_during_kill):
                raise MutationPipelineError("active_kill")

    def _commit_intent(
        self, request: MutationRequest, authorization: MutationAuthorization
    ) -> str:
        try:
            with self._sessions.begin() as session:
                binding = session.get(AccountBinding, request.account_binding_id)
                decision = session.get(StrategyDecision, request.strategy_decision_id)
                policy = session.get(PolicyVersion, request.policy_version_id)
                risk = session.get(RiskDecision, request.risk_decision_id)
                if binding is None or not binding.is_active \
                        or binding.installation_id != request.installation_id \
                        or binding.provider_account_id != str(request.account_id):
                    raise MutationPipelineError("active_exact_account_required")
                if decision is None or decision.installation_id != request.installation_id:
                    raise MutationPipelineError("local_strategy_decision_required")
                if policy is None or not policy.is_active \
                        or policy.installation_id != request.installation_id:
                    raise MutationPipelineError("active_policy_required")
                if risk is None or not risk.allowed or risk.policy_version_id != policy.id:
                    raise MutationPipelineError("allowed_risk_decision_required")
                row = OrderIntent(
                    installation_id=request.installation_id,
                    account_binding_id=binding.id,
                    strategy_decision_id=decision.id,
                    policy_version_id=policy.id,
                    risk_decision_id=risk.id,
                    action=request.action,
                    custom_tag=request.custom_tag,
                    contract_id=request.contract_id,
                    side=request.side,
                    order_type=request.order_type,
                    quantity=1,
                    target_provider_id=(str(request.target_provider_id)
                                        if request.target_provider_id is not None else None),
                    limit_price=request.limit_price,
                    stop_price=request.stop_price,
                    trail_price=request.trail_price,
                    request_hash=request_hash(request),
                    authorization_expires_at=authorization.expires_at,
                    origin=request.origin,
                    risk_classification="allowed",
                    state="committed",
                    created_at=self._clock(),
                )
                session.add(row)
                session.flush()
                return row.id
        except IntegrityError as exc:
            raise MutationPipelineError("duplicate_custom_tag") from exc

    def _commit_attempt(self, intent_id: str) -> str:
        with self._sessions.begin() as session:
            existing = session.scalar(select(SubmissionAttempt).where(
                SubmissionAttempt.intent_id == intent_id
            ))
            if existing is not None:
                raise MutationPipelineError("mutation_attempt_already_exists")
            row = SubmissionAttempt(
                intent_id=intent_id, attempt_number=1, state="boundary_committed",
                started_at=self._clock(),
            )
            session.add(row)
            session.flush()
            return row.id

    def _call_once(self, token: str, request: MutationRequest) -> MutationResult:
        common = {"account_id": request.account_id}
        if request.action == "place":
            return self._client.place_order(
                token, **common, contract_id=request.contract_id,
                order_type=request.order_type, side=request.side, quantity=1,
                custom_tag=request.custom_tag, limit_price=request.limit_price,
                stop_price=request.stop_price, trail_price=request.trail_price,
            )
        if request.action == "cancel":
            return self._client.cancel_order(
                token, **common, order_id=request.target_provider_id
            )
        if request.action == "modify":
            return self._client.modify_order(
                token, **common, order_id=request.target_provider_id, quantity=1,
                limit_price=request.limit_price, stop_price=request.stop_price,
                trail_price=request.trail_price,
            )
        if request.action == "close":
            return self._client.close_position(
                token, **common, contract_id=request.contract_id
            )
        return self._client.partial_close_position(
            token, **common, contract_id=request.contract_id, quantity=1
        )

    def _record_acknowledgement(
        self, intent_id: str, attempt_id: str, result: MutationResult, *, state: str
    ) -> None:
        self._failure_hook("before_ack_commit")
        normalized = {
            "classification": result.classification,
            "provider_error_code": result.provider_error_code,
            "provider_order_id": result.provider_order_id,
        }
        with self._sessions.begin() as session:
            attempt = session.get(SubmissionAttempt, attempt_id)
            intent = session.get(OrderIntent, intent_id)
            if attempt is None or intent is None:
                raise MutationPipelineError("journal_boundary_missing")
            session.add(Acknowledgement(
                attempt_id=attempt_id,
                classification=result.classification,
                provider_order_id=(str(result.provider_order_id)
                                   if result.provider_order_id is not None else None),
                response_hash=sha256(json.dumps(
                    normalized, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")).hexdigest(),
                acknowledged_at=self._clock(),
            ))
            attempt.state = state
            attempt.completed_at = self._clock()
            intent.state = state

    def _mark_ambiguous(self, intent_id: str, attempt_id: str, reason: str) -> None:
        with self._sessions.begin() as session:
            intent = session.get(OrderIntent, intent_id)
            attempt = session.get(SubmissionAttempt, attempt_id)
            if intent is None or attempt is None:
                raise MutationPipelineError("journal_boundary_missing")
            intent.state = "ambiguous"
            attempt.state = "ambiguous"
            attempt.completed_at = self._clock()
            binding_id = intent.account_binding_id
        self._acquire_lock(binding_id, reason)

    def _acquire_lock(self, account_binding_id: str, reason: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(select(ReconciliationLock).where(
                ReconciliationLock.account_binding_id == account_binding_id
            ))
            if row is None:
                session.add(ReconciliationLock(
                    account_binding_id=account_binding_id, active=True,
                    reason=reason, acquired_at=self._clock(),
                ))
            else:
                row.active = True
                row.reason = reason
                row.acquired_at = self._clock()
                row.resolved_at = None
                row.resolution_classification = None
                row.resolution_evidence = None

    @staticmethod
    def _assert_preflight(
        request: MutationRequest,
        authorization: MutationAuthorization,
        preflight: MutationPreflight,
    ) -> None:
        if preflight.exact_account_id != request.account_id \
                or preflight.exact_account_id != authorization.exact_account_id:
            raise MutationPipelineError("preflight_account_switch_detected")
        checks = {
            "provider_unavailable": preflight.provider_available,
            "preflight_reconciliation_not_clean": preflight.reconciliation_clean,
            "local_outstanding_intent": preflight.local_outstanding_clean,
            "preflight_market_stale": preflight.market_fresh,
            "preflight_clock_unhealthy": preflight.clock_healthy,
            "preflight_rate_budget_unavailable": preflight.rate_budget_available,
        }
        for classification, passed in checks.items():
            if not passed:
                raise MutationPipelineError(classification)
        if not preflight.provider_state_hash:
            raise MutationPipelineError("preflight_provider_state_missing")
