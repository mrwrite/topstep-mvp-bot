from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_string() -> str:
    return str(uuid4())


class LocalBase(DeclarativeBase):
    pass


class Installation(LocalBase):
    __tablename__ = "installations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    software_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="disabled", nullable=False)
    __table_args__ = (
        CheckConstraint("length(id) = 36", name="ck_installation_uuid"),
    )


class LifecycleTransition(LocalBase):
    __tablename__ = "lifecycle_transitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    installation: Mapped[Installation] = relationship()


class AccountBinding(LocalBase):
    __tablename__ = "account_bindings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    credential_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_account_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    account_attestation: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    installation: Mapped[Installation] = relationship()
    __table_args__ = (
        UniqueConstraint("installation_id", "provider_account_id", "credential_generation",
                         name="uq_local_account_binding"),
        CheckConstraint("credential_generation > 0", name="ck_local_binding_generation"),
        CheckConstraint("account_attestation IN ('practice','trading_combine')",
                        name="ck_local_account_attestation"),
    )


class PolicyVersion(LocalBase):
    __tablename__ = "policy_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    installation: Mapped[Installation] = relationship()
    __table_args__ = (
        UniqueConstraint("installation_id", "version", name="uq_local_policy_version"),
        UniqueConstraint("installation_id", "checksum", name="uq_local_policy_checksum"),
        CheckConstraint("version > 0", name="ck_local_policy_version"),
    )


class Consent(LocalBase):
    __tablename__ = "consents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    credential_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_binding: Mapped[AccountBinding] = relationship()
    policy_version: Mapped[PolicyVersion] = relationship()


class QualificationEvidence(LocalBase):
    __tablename__ = "qualification_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="CASCADE"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KillState(LocalBase):
    __tablename__ = "kill_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="installation", nullable=False)
    scope_key: Mapped[str] = mapped_column(String(128), default="self", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), default="initial_fail_closed", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_local_kill_version"),
        CheckConstraint(
            "scope IN ('installation','account','strategy_run','reconciliation','stale_data','loss','authentication','manual')",
            name="ck_local_kill_scope",
        ),
        UniqueConstraint("installation_id", "scope", "scope_key", name="uq_local_kill_scope"),
    )


class MarketInput(LocalBase):
    __tablename__ = "market_inputs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    input_identity: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="topstep_simulated", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StrategyDecision(LocalBase):
    __tablename__ = "strategy_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    market_input_id: Mapped[str] = mapped_column(ForeignKey("market_inputs.id", ondelete="RESTRICT"), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    market_input: Mapped[MarketInput] = relationship()


class ProposedIntent(LocalBase):
    __tablename__ = "proposed_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    strategy_decision_id: Mapped[str] = mapped_column(ForeignKey("strategy_decisions.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        CheckConstraint("quantity = 1", name="ck_local_proposal_quantity_one"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_local_proposal_side"),
    )


class RiskDecision(LocalBase):
    __tablename__ = "risk_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    proposed_intent_id: Mapped[str] = mapped_column(ForeignKey("proposed_intents.id", ondelete="RESTRICT"), nullable=False, unique=True)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    classifications: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OrderIntent(LocalBase):
    __tablename__ = "order_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="RESTRICT"), nullable=False)
    strategy_decision_id: Mapped[str] = mapped_column(ForeignKey("strategy_decisions.id", ondelete="RESTRICT"), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    risk_decision_id: Mapped[str | None] = mapped_column(ForeignKey("risk_decisions.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(24), default="place", nullable=False)
    custom_tag: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    target_provider_id: Mapped[str | None] = mapped_column(String(128))
    limit_price: Mapped[str | None] = mapped_column(String(64))
    stop_price: Mapped[str | None] = mapped_column(String(64))
    trail_price: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(128), default="legacy", nullable=False)
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(32), default="personal_device", nullable=False)
    risk_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="committed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decision: Mapped[StrategyDecision] = relationship()
    __table_args__ = (
        CheckConstraint("quantity = 1", name="ck_local_intent_quantity_one"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_local_intent_side"),
        CheckConstraint(
            "action IN ('place','cancel','modify','close','partial_close')",
            name="ck_local_intent_action",
        ),
        CheckConstraint("origin = 'personal_device'", name="ck_local_intent_origin"),
    )


class SubmissionAttempt(LocalBase):
    __tablename__ = "submission_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    intent_id: Mapped[str] = mapped_column(ForeignKey("order_intents.id", ondelete="RESTRICT"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="boundary_committed", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intent: Mapped[OrderIntent] = relationship()
    __table_args__ = (
        UniqueConstraint("intent_id", "attempt_number", name="uq_local_submission_attempt"),
        CheckConstraint("attempt_number > 0", name="ck_local_attempt_number"),
    )


class Acknowledgement(LocalBase):
    __tablename__ = "acknowledgements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("submission_attempts.id", ondelete="RESTRICT"), nullable=False, unique=True)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128))
    response_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProviderOrder(LocalBase):
    __tablename__ = "provider_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="RESTRICT"), nullable=False)
    intent_id: Mapped[str | None] = mapped_column(ForeignKey("order_intents.id", ondelete="SET NULL"))
    provider_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    custom_tag: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint("account_binding_id", "provider_order_id", name="uq_local_provider_order"),
    )


class Trade(LocalBase):
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="RESTRICT"), nullable=False)
    provider_trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128))
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[str] = mapped_column(String(64), nullable=False)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("account_binding_id", "provider_trade_id", name="uq_local_provider_trade"),
    )


class PositionSnapshot(LocalBase):
    __tablename__ = "position_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_price: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReconciliationRun(LocalBase):
    __tablename__ = "reconciliation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="RESTRICT"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    result_classification: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    checkpoints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationLock(LocalBase):
    __tablename__ = "reconciliation_locks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="CASCADE"), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_classification: Mapped[str | None] = mapped_column(String(64))
    resolution_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class AuditEvent(LocalBase):
    __tablename__ = "audit_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), default=uuid_string, nullable=False, unique=True)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        CheckConstraint("length(event_id) = 36", name="ck_local_audit_uuid"),
        CheckConstraint("length(correlation_id) = 36", name="ck_local_audit_correlation_uuid"),
        {"sqlite_autoincrement": True},
    )


class TelemetryOutbox(LocalBase):
    __tablename__ = "telemetry_outbox"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), default=uuid_string, nullable=False, unique=True)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="ck_local_telemetry_schema"),
        CheckConstraint("attempt_count >= 0", name="ck_local_telemetry_attempts"),
        CheckConstraint("status IN ('pending','sending','acknowledged','terminal')",
                        name="ck_local_telemetry_status"),
        Index("ix_local_telemetry_delivery", "status", "sequence"),
        {"sqlite_autoincrement": True},
    )


class ProviderRateBudget(LocalBase):
    __tablename__ = "provider_rate_budgets"
    bucket: Mapped[str] = mapped_column(String(32), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now,
                                                  onupdate=utc_now, nullable=False)
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="ck_local_provider_rate_count"),
    )


class ActivationGrant(LocalBase):
    __tablename__ = "activation_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    installation_id: Mapped[str] = mapped_column(ForeignKey("installations.id", ondelete="CASCADE"), nullable=False)
    account_binding_id: Mapped[str] = mapped_column(ForeignKey("account_bindings.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    consent_id: Mapped[str] = mapped_column(ForeignKey("consents.id", ondelete="RESTRICT"), nullable=False)
    credential_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    boot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="armed", nullable=False)
    armed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_intent_hash: Mapped[str | None] = mapped_column(String(128))
    first_intent_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_intent_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_intent_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_intent_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automated_sessions_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("credential_generation > 0", name="ck_local_activation_generation"),
        CheckConstraint("state IN ('armed','first_order_used','reviewed','invalidated','expired')",
                        name="ck_local_activation_state"),
        Index("ix_local_activation_current", "installation_id", "state", "expires_at"),
    )
