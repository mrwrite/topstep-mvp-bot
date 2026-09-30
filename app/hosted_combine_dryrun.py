"""Durable hosted-Combine risk policy and order-free strategy preview.

This module is intentionally isolated from the paper-order and provider-order
consumers. It evaluates only persisted, tenant-owned market inputs.
"""
from __future__ import annotations

import hashlib
import os
import math
from datetime import timedelta
from datetime import datetime as DateTime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from . import models
from .authorization import OperatorContext, TenantContext
from .simulation_evaluation import DurableRunError, evaluate_rsi_threshold
from .strategy import STRATEGY_NAME, STRATEGY_VERSION
from .tenant_repository import TenantRepository
from .time_utils import as_utc, utc_now
from .topstep_onboarding import execution_eligibility


CONSENT_VERSION = "hosted-combine-dry-run-v1"
STRATEGY_KEY = f"{STRATEGY_NAME}@{STRATEGY_VERSION}"
CONSENT_TEXT = (
    "I represent that the selected account is a Topstep Trading Combine and is not an Express Funded "
    "or Live Funded account. Automated analysis may affect decisions; the current dry-run mode submits "
    "no orders. A future separately enabled execution mode could affect Combine evaluation results. "
    "I remain responsible for Topstep rules and account monitoring, may disconnect and revoke my API "
    "key, and understand emergency controls may suspend activity without notice. This consent does not "
    "waive the application's security obligations."
)
POLICY_FIELDS = {
    "allowed_strategies", "allowed_instruments", "max_order_quantity", "max_open_position",
    "max_orders_per_session", "max_orders_per_day", "max_consecutive_losses",
    "max_daily_realized_loss", "max_session_loss", "max_stale_data_seconds",
    "schedule", "cooldown_seconds", "dry_run_enabled", "provider_order_execution_enabled",
}


class HostedDryRunError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_policy(policy: dict) -> None:
    if not isinstance(policy, dict) or POLICY_FIELDS - set(policy) or set(policy) - POLICY_FIELDS:
        raise HostedDryRunError("risk_policy_incomplete")
    if (not policy["allowed_strategies"] or not policy["allowed_instruments"]
            or not isinstance(policy["allowed_strategies"], list)
            or not isinstance(policy["allowed_instruments"], list)
            or any(not isinstance(item, str) or "@" not in item or not item.strip()
                   for item in policy["allowed_strategies"])
            or any(not isinstance(item, str) or not item.strip() for item in policy["allowed_instruments"])):
        raise HostedDryRunError("risk_policy_empty_allowlist")
    if policy["provider_order_execution_enabled"] is not False or policy["dry_run_enabled"] is not True:
        raise HostedDryRunError("provider_mutation_must_remain_disabled")
    if type(policy["max_order_quantity"]) is not int or policy["max_order_quantity"] != 1:
        raise HostedDryRunError("hosted_beta_quantity_must_equal_one")
    integer_fields = ("max_open_position", "max_orders_per_session", "max_orders_per_day",
                      "max_consecutive_losses", "max_stale_data_seconds", "cooldown_seconds")
    if any(type(policy[name]) is not int or policy[name] < 0 for name in integer_fields):
        raise HostedDryRunError("risk_policy_invalid_limit")
    if (isinstance(policy["max_daily_realized_loss"], bool)
            or not isinstance(policy["max_daily_realized_loss"], (int, float))
            or not math.isfinite(policy["max_daily_realized_loss"])
            or policy["max_daily_realized_loss"] < 0
            or isinstance(policy["max_session_loss"], bool)
            or not isinstance(policy["max_session_loss"], (int, float))
            or not math.isfinite(policy["max_session_loss"])
            or policy["max_session_loss"] < 0):
        raise HostedDryRunError("risk_policy_invalid_loss_limit")
    schedule = policy["schedule"]
    if not isinstance(schedule, dict) or not isinstance(schedule.get("timezone"), str):
        raise HostedDryRunError("risk_policy_schedule_missing")
    try:
        ZoneInfo(schedule["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise HostedDryRunError("risk_policy_timezone_invalid") from exc
    weekdays = schedule.get("weekdays", [0, 1, 2, 3, 4])
    if (not isinstance(weekdays, list) or any(type(day) is not int or day < 0 or day > 6 for day in weekdays)
            or not isinstance(schedule.get("start", "00:00"), str)
            or not isinstance(schedule.get("end", "23:59"), str)):
        raise HostedDryRunError("risk_policy_schedule_invalid")
    try:
        DateTime.strptime(schedule.get("start", "00:00"), "%H:%M")
        DateTime.strptime(schedule.get("end", "23:59"), "%H:%M")
    except ValueError as exc:
        raise HostedDryRunError("risk_policy_schedule_invalid") from exc


def create_policy(db: Session, operator: OperatorContext, *, tenant_id: int, integration_id: int,
                  provider_account_id: str, policy: dict, required_consent_version: str,
                  expires_at=None) -> models.HostedCombineRiskPolicy:
    if (operator.target_tenant_id != tenant_id or as_utc(operator.expires_at) <= utc_now()
            or not operator.purpose.strip() or not operator.case_id.strip()):
        raise HostedDryRunError("operator_context_invalid")
    if not os.getenv("TOPSTEP_BETA_COHORT_ID"):
        raise HostedDryRunError("cohort_configuration_missing")
    validate_policy(policy)
    repo = TenantRepository(db, TenantContext(tenant_id, "hosted-policy-operator",
                                               actor_user_id=operator.actor_user_id,
                                               source="operator", correlation_id=operator.correlation_id,
                                               expires_at=operator.expires_at))
    integration = repo.get(models.PlatformIntegration, integration_id, lock=True)
    approval = repo.first(models.TopstepAccountApproval,
                          models.TopstepAccountApproval.integration_id == integration_id,
                          models.TopstepAccountApproval.provider_account_id == str(provider_account_id),
                          models.TopstepAccountApproval.state == "approved",
                          models.TopstepAccountApproval.revoked_at.is_(None), lock=True)
    if not integration or integration.status != "approved" or not approval or as_utc(approval.expires_at) <= utc_now():
        raise HostedDryRunError("approved_account_required")
    now = utc_now()
    for old in repo.list(models.HostedCombineRiskPolicy,
                         models.HostedCombineRiskPolicy.integration_id == integration_id,
                         models.HostedCombineRiskPolicy.state == "active", lock=True):
        old.state = "revoked"
        old.version += 1
    prior_dry_runs = repo.list(
        models.HostedCombineDryRun,
        models.HostedCombineDryRun.integration_id == integration_id,
        models.HostedCombineDryRun.state.in_(
            ("requested", "eligibility_checking", "market_data_loading", "evaluating", "risk_evaluating")),
        lock=True,
    )
    for dry_run in prior_dry_runs:
        dry_run.state = "canceled"
        dry_run.result_classification = "risk_policy_changed"
        dry_run.completed_at = now
        dry_run.lease_owner = None
        dry_run.lease_expires_at = None
    prior_ids = [item.id for item in repo.list(
        models.HostedCombineDryRun, models.HostedCombineDryRun.integration_id == integration_id
    )]
    if prior_ids:
        for proposal in repo.list(models.HostedCombineProposal,
                                  models.HostedCombineProposal.dry_run_id.in_(prior_ids), lock=True):
            proposal.expires_at = now
    previous = repo.list(models.HostedCombineRiskPolicy,
                         models.HostedCombineRiskPolicy.integration_id == integration_id,
                         order_by=(models.HostedCombineRiskPolicy.policy_version.desc(),), limit=1)
    prior = previous[0] if previous else None
    row = repo.add(models.HostedCombineRiskPolicy(
        id=str(uuid4()), user_id=tenant_id,
        cohort_id=os.getenv("TOPSTEP_BETA_COHORT_ID", ""),
        tester_user_id=tenant_id, integration_id=integration_id,
        provider_account_id=str(provider_account_id), policy_version=(prior.policy_version + 1 if prior else 1),
        state="active", policy=policy, required_consent_version=required_consent_version,
        effective_at=now, expires_at=expires_at, approved_by_operator_id=operator.actor_user_id,
        operator_context={"purpose": operator.purpose, "case_id": operator.case_id,
                          "correlation_id": operator.correlation_id},
    ))
    db.flush()
    return row


def accept_consent(db: Session, tenant: TenantContext, *, integration_id: int,
                   provider_account_id: str, policy_version: int,
                   consent_version: str = CONSENT_VERSION) -> models.HostedCombineConsent:
    repo = TenantRepository(db, tenant)
    if consent_version != CONSENT_VERSION:
        raise HostedDryRunError("consent_version_mismatch")
    decision = execution_eligibility(db, tenant, integration_id=integration_id,
                                     provider_account_id=provider_account_id)
    if not decision.allowed:
        raise HostedDryRunError(decision.reason)
    policy = repo.first(models.HostedCombineRiskPolicy,
                        models.HostedCombineRiskPolicy.integration_id == integration_id,
                        models.HostedCombineRiskPolicy.policy_version == policy_version,
                        models.HostedCombineRiskPolicy.state == "active")
    approval = repo.first(models.TopstepAccountApproval,
                          models.TopstepAccountApproval.integration_id == integration_id,
                          models.TopstepAccountApproval.provider_account_id == provider_account_id,
                          models.TopstepAccountApproval.state == "approved",
                          models.TopstepAccountApproval.revoked_at.is_(None))
    if (not policy or policy.provider_account_id != provider_account_id or not approval
            or as_utc(policy.effective_at) > utc_now()
            or (policy.expires_at and as_utc(policy.expires_at) <= utc_now())):
        raise HostedDryRunError("policy_or_approval_not_current")
    credential = repo.first(models.TopstepCredential,
                            models.TopstepCredential.integration_id == integration_id,
                            models.TopstepCredential.is_current == 1)
    prior = repo.first(models.HostedCombineConsent,
                       models.HostedCombineConsent.integration_id == integration_id,
                       models.HostedCombineConsent.credential_generation == credential.credential_generation,
                       models.HostedCombineConsent.provider_account_id == provider_account_id,
                       models.HostedCombineConsent.approval_id == approval.id,
                       models.HostedCombineConsent.policy_version == policy_version,
                       models.HostedCombineConsent.consent_version == consent_version,
                       models.HostedCombineConsent.revoked_at.is_(None))
    if prior:
        return prior
    row = repo.add(models.HostedCombineConsent(
        id=str(uuid4()), user_id=tenant.user_id, integration_id=integration_id,
        credential_generation=credential.credential_generation,
        provider_account_id=provider_account_id, approval_id=approval.id,
        policy_version=policy_version, consent_version=consent_version,
        consent_text=CONSENT_TEXT, accepted_at=utc_now(), correlation_id=tenant.correlation_id,
    ))
    db.add(models.SecurityAuditEvent(
        actor_user_id=tenant.actor_id, target_user_id=tenant.user_id,
        event_type="hosted_combine_consent", action="consent_accepted", outcome="success",
        event_metadata={"correlation_id": tenant.correlation_id, "integration_id": integration_id,
                        "policy_version": policy_version, "consent_version": consent_version},
    ))
    db.flush()
    return row


def request_dry_run(db: Session, tenant: TenantContext, *, integration_id: int,
                    provider_account_id: str, policy_version: int,
                    idempotency_key: str) -> tuple[models.HostedCombineDryRun, bool]:
    repo = TenantRepository(db, tenant)
    decision = execution_eligibility(db, tenant, integration_id=integration_id,
                                     provider_account_id=provider_account_id)
    if not decision.allowed:
        raise HostedDryRunError(decision.reason)
    policy = repo.first(models.HostedCombineRiskPolicy,
                        models.HostedCombineRiskPolicy.integration_id == integration_id,
                        models.HostedCombineRiskPolicy.policy_version == policy_version,
                        models.HostedCombineRiskPolicy.state == "active")
    if (not policy or policy.provider_account_id != provider_account_id
            or as_utc(policy.effective_at) > utc_now()
            or (policy.expires_at and as_utc(policy.expires_at) <= utc_now())):
        raise HostedDryRunError("risk_policy_not_current")
    validate_policy(policy.policy)
    consents = repo.list(models.HostedCombineConsent,
                         models.HostedCombineConsent.integration_id == integration_id,
                         models.HostedCombineConsent.credential_generation == decision.credential_generation,
                         models.HostedCombineConsent.provider_account_id == provider_account_id,
                         models.HostedCombineConsent.approval_id == approval.id,
                         models.HostedCombineConsent.policy_version == policy_version,
                         models.HostedCombineConsent.consent_version == policy.required_consent_version,
                         models.HostedCombineConsent.revoked_at.is_(None),
                         order_by=(models.HostedCombineConsent.accepted_at.desc(),), limit=1)
    consent = consents[0] if consents else None
    approval = repo.first(models.TopstepAccountApproval,
                          models.TopstepAccountApproval.integration_id == integration_id,
                          models.TopstepAccountApproval.provider_account_id == provider_account_id,
                          models.TopstepAccountApproval.state == "approved",
                          models.TopstepAccountApproval.revoked_at.is_(None))
    matching_runs = repo.list(models.SimulationRun,
                              models.SimulationRun.integration_id == integration_id,
                              order_by=(models.SimulationRun.updated_at.desc(),), limit=1)
    run = matching_runs[0] if matching_runs else None
    matching_markets = (repo.list(models.SimulationMarketInput,
                                  models.SimulationMarketInput.run_id == run.id,
                                  models.SimulationMarketInput.status == "processed",
                                  order_by=(models.SimulationMarketInput.event_at.desc(),), limit=1)
                        if run else [])
    market = matching_markets[0] if matching_markets else None
    if not consent or not approval or not run or not market:
        raise HostedDryRunError("current_consent_approval_and_market_input_required")
    if run.credential_generation != decision.credential_generation:
        raise HostedDryRunError("credential_generation_mismatch")
    if str((run.configuration or {}).get("account_id")) != str(provider_account_id):
        raise HostedDryRunError("run_account_mismatch")
    if run.security_epoch != run.configuration.get("security_epoch"):
        raise HostedDryRunError("security_epoch_mismatch")
    if run.strategy_version != STRATEGY_VERSION:
        raise HostedDryRunError("unsupported_strategy_version")
    if STRATEGY_KEY not in policy.policy["allowed_strategies"]:
        raise HostedDryRunError("strategy_not_allowed")
    if run.symbol not in {str(x).upper() for x in policy.policy["allowed_instruments"]}:
        raise HostedDryRunError("instrument_not_allowed")
    run_id, market_input_id = run.id, market.id
    prior = repo.first(models.HostedCombineDryRun,
                       models.HostedCombineDryRun.idempotency_key == idempotency_key)
    if prior:
        if prior.integration_id != integration_id or prior.market_input_id != market_input_id:
            raise HostedDryRunError("idempotency_conflict")
        return prior, True
    identity = hashlib.sha256(f"{tenant.user_id}:{integration_id}:{market.id}:{policy_version}:{consent.id}".encode()).hexdigest()
    existing = repo.first(models.HostedCombineDryRun, models.HostedCombineDryRun.stable_identity == identity)
    if existing:
        return existing, True
    row = repo.add(models.HostedCombineDryRun(
        id=str(uuid4()), user_id=tenant.user_id, integration_id=integration_id,
        credential_generation=decision.credential_generation, provider_account_id=provider_account_id,
        approval_id=approval.id, approval_version=approval.version,
        security_epoch=run.security_epoch, policy_id=policy.id, policy_version=policy.policy_version,
        consent_id=consent.id, strategy_name=STRATEGY_NAME, strategy_version=STRATEGY_VERSION,
        configuration_hash=run.configuration_hash, instrument=run.symbol,
        source_run_id=run.id, market_input_id=market.id, market_identity=market.source_identity,
        state="requested", idempotency_key=idempotency_key, stable_identity=identity,
        correlation_id=tenant.correlation_id, causation_id=market.source_identity, requested_at=utc_now(),
    ))
    db.add(models.SecurityAuditEvent(
        actor_user_id=tenant.actor_id, target_user_id=tenant.user_id,
        event_type="hosted_combine_dry_run", action="dry_run_requested", outcome="accepted",
        event_metadata={"correlation_id": tenant.correlation_id, "dry_run_id": row.id,
                        "policy_version": policy_version},
    ))
    db.flush()
    return row, False


def process_pending_dry_runs(db: Session, *, worker_id: str, limit: int = 10,
                             lease_seconds: int = 30, failure_injector=None) -> int:
    inject = failure_injector or (lambda _stage: None)
    now = utc_now()
    rows = (db.query(models.HostedCombineDryRun)
            .filter(models.HostedCombineDryRun.state.in_(("requested", "evaluating")),
                    (models.HostedCombineDryRun.lease_expires_at.is_(None)
                     | (models.HostedCombineDryRun.lease_expires_at <= now)))
            .order_by(models.HostedCombineDryRun.requested_at)
            .with_for_update(skip_locked=True).limit(limit).all())
    if not rows:
        return 0
    claimed = []
    for row in rows:
        row.lease_owner = worker_id
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.fencing_token += 1
        row.attempt_count += 1
        row.state = "evaluating"
        claimed.append((row.id, row.fencing_token))
    db.commit()
    processed = 0
    for run_id, fence in claimed:
        try:
            candidate = db.query(models.HostedCombineDryRun).filter_by(id=run_id).first()
            if candidate is None:
                db.rollback()
                continue
            db.query(models.PlatformIntegration).filter_by(
                id=candidate.integration_id, user_id=candidate.user_id).with_for_update().one_or_none()
            row = (db.query(models.HostedCombineDryRun).filter_by(id=run_id)
                   .with_for_update().one())
            if (row.lease_owner != worker_id or row.fencing_token != fence
                    or as_utc(row.lease_expires_at) <= utc_now()):
                db.rollback()
                continue
            tenant = TenantContext(row.user_id, "hosted-dry-run-worker", source="worker")
            inject("before_eligibility")
            eligibility = execution_eligibility(db, tenant, integration_id=row.integration_id,
                                                provider_account_id=row.provider_account_id)
            policy = db.query(models.HostedCombineRiskPolicy).filter_by(
                id=row.policy_id, user_id=row.user_id, state="active", policy_version=row.policy_version).first()
            consent = db.query(models.HostedCombineConsent).filter_by(
                id=row.consent_id, user_id=row.user_id, revoked_at=None).first()
            approval = db.query(models.TopstepAccountApproval).filter_by(
                id=row.approval_id, user_id=row.user_id, state="approved", revoked_at=None).first()
            market = db.query(models.SimulationMarketInput).filter_by(
                id=row.market_input_id, run_id=row.source_run_id, user_id=row.user_id, status="processed").first()
            run = db.query(models.SimulationRun).filter_by(
                id=row.source_run_id, user_id=row.user_id).first()
            if (not eligibility.allowed or not policy or not consent or not approval or not market or not run
                    or (policy.expires_at and as_utc(policy.expires_at) <= utc_now())
                    or as_utc(policy.effective_at) > utc_now()
                    or consent.integration_id != row.integration_id
                    or consent.credential_generation != row.credential_generation
                    or consent.provider_account_id != row.provider_account_id
                    or consent.approval_id != row.approval_id
                    or consent.policy_version != row.policy_version
                    or approval.version != row.approval_version
                    or approval.credential_generation != row.credential_generation
                    or approval.provider_account_id != row.provider_account_id
                    or run.integration_id != row.integration_id
                    or run.credential_generation != row.credential_generation
                    or run.security_epoch != row.security_epoch
                    or run.configuration_hash != row.configuration_hash
                    or market.source_identity != row.market_identity):
                row.state, row.result_classification = "denied", "eligibility_or_source_state_changed"
                row.risk_results = [{"check": "current_state", "passed": False,
                                     "classification": "denied"}]
            else:
                inject("before_strategy")
                cfg = policy.policy
                age = max(0, int((utc_now() - as_utc(market.event_at)).total_seconds()))
                from zoneinfo import ZoneInfo
                local_now = as_utc(market.event_at).astimezone(ZoneInfo(cfg["schedule"]["timezone"]))
                schedule = cfg["schedule"]
                weekdays = schedule.get("weekdays", list(range(5)))
                start = str(schedule.get("start", "00:00"))
                end = str(schedule.get("end", "23:59"))
                now_hm = local_now.strftime("%H:%M")
                schedule_ok = local_now.weekday() in {int(x) for x in weekdays} and start <= now_hm <= end
                parameters = {
                    "buy_threshold": int((run.configuration or {}).get("buy_threshold", 30)),
                    "sell_threshold": int((run.configuration or {}).get("sell_threshold", 70)),
                    "min_bars": int((run.configuration or {}).get("min_bars", 30)),
                }
                from .risk_service import risk_service
                run_kill = risk_service.find_active_kill_switch(
                    db, user_id=row.user_id, integration_id=row.integration_id,
                    account_id=row.provider_account_id, bot_session_id=run.id,
                )
                global_kill = risk_service.find_active_kill_switch(
                    db, user_id=row.user_id, integration_id=None, account_id=None)
                tenant_kill = risk_service.find_active_kill_switch(
                    db, user_id=row.user_id, integration_id=row.integration_id, account_id=None)
                account_kill = risk_service.find_active_kill_switch(
                    db, user_id=row.user_id, integration_id=row.integration_id,
                    account_id=row.provider_account_id)
                current_credential = db.query(models.TopstepCredential).filter_by(
                    user_id=row.user_id, integration_id=row.integration_id,
                    credential_generation=row.credential_generation, is_current=1).first()
                current_session = db.query(models.TopstepProviderSession).filter_by(
                    user_id=row.user_id, integration_id=row.integration_id,
                    credential_generation=row.credential_generation, state="valid",
                    revoked_at=None, deleted_at=None).first()
                current_snapshot = db.query(models.TopstepDiscoverySnapshot).filter_by(
                    user_id=row.user_id, integration_id=row.integration_id,
                    credential_generation=row.credential_generation, security_epoch=row.security_epoch,
                    is_current=1).filter(models.TopstepDiscoverySnapshot.expires_at > utc_now()).first()
                current_attestation = db.query(models.TopstepCombineAttestation).filter_by(
                    user_id=row.user_id, integration_id=row.integration_id,
                    credential_generation=row.credential_generation, provider_account_id=row.provider_account_id,
                    revoked_at=None).filter(models.TopstepCombineAttestation.expires_at > utc_now()).first()
                try:
                    from .topstep_session_security import require_current_epoch
                    require_current_epoch(db, row.security_epoch)
                    epoch_ok = True
                except Exception:
                    epoch_ok = False
                policy_effective = bool(policy and policy.state == "active"
                                        and as_utc(policy.effective_at) <= utc_now()
                                        and (not policy.expires_at or as_utc(policy.expires_at) > utc_now()))
                checks = [
                    {"check": "integration_eligibility", "passed": eligibility.allowed},
                    {"check": "credential_generation", "passed": current_credential is not None},
                    {"check": "provider_session", "passed": bool(current_session and current_session.token_encrypted
                        and as_utc(current_session.expires_at) > utc_now())},
                    {"check": "account_discovery", "passed": current_snapshot is not None},
                    {"check": "combine_attestation", "passed": current_attestation is not None},
                    {"check": "exact_administrator_approval", "passed": bool(approval and approval.provider_account_id == row.provider_account_id
                        and approval.credential_generation == row.credential_generation
                        and approval.expires_at and as_utc(approval.expires_at) > utc_now())},
                    {"check": "security_epoch", "passed": epoch_ok},
                    {"check": "risk_policy_current", "passed": policy_effective},
                    {"check": "tester_consent_current", "passed": bool(consent and consent.policy_version == row.policy_version
                        and consent.credential_generation == row.credential_generation
                        and consent.approval_id == row.approval_id)},
                    {"check": "strategy_allowlist", "passed": f"{row.strategy_name}@{row.strategy_version}" in cfg["allowed_strategies"]},
                    {"check": "instrument_allowlist", "passed": row.instrument in {str(x).upper() for x in cfg["allowed_instruments"]}},
                    {"check": "quantity_limit", "passed": cfg["max_order_quantity"] == 1},
                    {"check": "data_freshness", "passed": age <= cfg["max_stale_data_seconds"], "age_seconds": age},
                    {"check": "trading_schedule", "passed": schedule_ok},
                    {"check": "open_position_limit", "passed": False,
                     "classification": "provider_position_snapshot_unavailable"},
                    {"check": "daily_order_limit", "passed": False,
                     "classification": "provider_order_history_unavailable"},
                    {"check": "session_order_limit", "passed": False,
                     "classification": "provider_order_history_unavailable"},
                    {"check": "consecutive_loss_limit", "passed": False,
                     "classification": "provider_trade_history_unavailable"},
                    {"check": "daily_realized_loss_limit", "passed": False,
                     "classification": "provider_pnl_snapshot_unavailable"},
                    {"check": "total_session_loss_limit", "passed": False,
                     "classification": "provider_pnl_snapshot_unavailable"},
                    {"check": "global_kill", "passed": global_kill is None},
                    {"check": "tenant_kill", "passed": tenant_kill is None},
                    {"check": "account_kill", "passed": account_kill is None},
                    {"check": "run_kill", "passed": run_kill is None},
                    {"check": "reconciliation_state", "passed": False,
                     "classification": "provider_reconciliation_snapshot_unavailable"},
                    {"check": "recovery_state", "passed": epoch_ok and run.state not in {"degraded", "recovering", "failed"}},
                    {"check": "provider_error_cooldown", "passed": False,
                     "classification": "provider_failure_history_unavailable"},
                    {"check": "provider_order_execution_disabled", "passed": cfg["provider_order_execution_enabled"] is False},
                    {"check": "read_only_topstep_provider_verified", "passed": False},
                    {"check": "live_trading_rejected", "passed": True},
                ]
                if not all(x["passed"] for x in checks):
                    row.state, row.result_classification = "degraded", "read_only_provider_evidence_unavailable"
                    row.risk_results = checks
                else:
                    signal, rationale, snapshot, _ = evaluate_rsi_threshold(market.payload or {}, parameters)
                    if signal == "HOLD":
                        row.state, row.result_classification = "no_action", "no_strategy_action"
                        row.risk_results = checks
                    else:
                        proposal = models.HostedCombineProposal(
                            id=str(uuid4()), user_id=row.user_id, dry_run_id=row.id,
                            evaluation_identity=hashlib.sha256(
                                f"{row.stable_identity}:{market.content_hash}:{fence}".encode()).hexdigest(),
                            strategy_signal=signal, rationale=rationale, instrument=row.instrument,
                            side=signal, quantity=1, order_type="market", policy_version=row.policy_version,
                            risk_checks=checks, data_freshness_seconds=age, schedule_allowed=1,
                            status="dry_run_only", created_at=utc_now(), expires_at=utc_now() + timedelta(minutes=5),
                        )
                        db.add(proposal)
                        row.proposal_id = proposal.id
                        row.state, row.result_classification = "proposed", "dry_run_only"
                        row.risk_results = checks
            inject("before_result_commit")
            if as_utc(row.lease_expires_at) <= utc_now() or row.lease_owner != worker_id or row.fencing_token != fence:
                db.rollback()
                continue
            row.completed_at = utc_now()
            row.lease_owner = None
            row.lease_expires_at = None
            db.add(models.SecurityAuditEvent(
                actor_user_id=row.user_id, target_user_id=row.user_id,
                event_type="hosted_combine_dry_run", action="dry_run_completed",
                outcome=row.state,
                event_metadata={"dry_run_id": row.id, "correlation_id": row.correlation_id,
                                "policy_version": row.policy_version,
                                "classification": row.result_classification},
            ))
            db.commit()
            processed += 1
            inject("after_result_commit")
        except DurableRunError:
            db.rollback()
            failed = db.query(models.HostedCombineDryRun).filter_by(id=run_id).with_for_update().first()
            if failed and failed.fencing_token == fence:
                failed.state, failed.result_classification = "failed", "strategy_evaluation_failed"
                failed.failure_classification = "integrity_or_history_failure"
                failed.lease_owner = None
                failed.lease_expires_at = None
                failed.completed_at = utc_now()
                db.commit()
        except Exception:
            db.rollback()
            try:
                failed = db.query(models.HostedCombineDryRun).filter_by(id=run_id).with_for_update().first()
                if failed and failed.fencing_token == fence and failed.state == "evaluating":
                    failed.state = "failed"
                    failed.result_classification = "evaluation_failed_closed"
                    failed.failure_classification = "processing_failure"
                    failed.completed_at = utc_now()
                    failed.lease_owner = None
                    failed.lease_expires_at = None
                    db.commit()
            except Exception:
                db.rollback()
                raise
    return processed


def serialize_dry_run(row: models.HostedCombineDryRun, proposal: models.HostedCombineProposal | None = None) -> dict:
    return {
        "id": row.id, "state": row.state, "result_classification": row.result_classification,
        "risk_checks": row.risk_results or [], "failure_classification": row.failure_classification,
        "proposal": ({"id": proposal.id, "status": "dry_run_only", "strategy_signal": proposal.strategy_signal,
                      "rationale": proposal.rationale, "instrument": proposal.instrument,
                      "side": proposal.side, "quantity": proposal.quantity, "order_type": proposal.order_type,
                      "expires_at": proposal.expires_at} if proposal else None),
        "provider_order_submitted": False, "message": "No order was submitted.",
        "requested_at": row.requested_at, "completed_at": row.completed_at,
    }
