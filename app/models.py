from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text, Index, Float
from datetime import datetime
from .database import Base
from pydantic import BaseModel
from typing import Any, Optional
from .providers.types import IntegrationProvider

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    email_verified_at = Column(DateTime, nullable=True)
    display_name = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    preferred_contact_email = Column(String, nullable=True)
    trading_experience_level = Column(String, nullable=True)
    is_admin = Column(Integer, nullable=False, default=0)

    active_integration_id = Column(
        Integer,
        ForeignKey("platform_integrations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # User configurable trading rules
    buy_threshold = Column(Integer, default=30)
    sell_threshold = Column(Integer, default=70)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=False, index=True)
    purpose = Column(String, nullable=False, default="email_verification")
    sent_count = Column(Integer, nullable=False, default=1)
    last_sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_email_verification_tokens_user_consumed", "user_id", "consumed_at"),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_password_reset_tokens_user_consumed", "user_id", "consumed_at"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=False, unique=True, index=True)
    user_agent_summary = Column(String, nullable=True)
    ip_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_user_sessions_user_revoked", "user_id", "revoked_at"),
    )


class AccountRecoveryRequest(Base):
    __tablename__ = "account_recovery_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reference_id = Column(String, nullable=False, unique=True, index=True)
    contact_email = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, default="account_recovery")
    status = Column(String, nullable=False, default="open", index=True)
    sanitized_message = Column(Text, nullable=False)
    request_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_account_recovery_requests_user_status", "user_id", "status"),
    )


class LegalDocument(Base):
    __tablename__ = "legal_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_type = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    content_markdown = Column(Text, nullable=False)
    content_url = Column(String, nullable=True)
    required = Column(Integer, nullable=False, default=1)
    active = Column(Integer, nullable=False, default=1, index=True)
    effective_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    document_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_legal_documents_type_version", "document_type", "version", unique=True),
        Index("ix_legal_documents_required_active", "required", "active"),
    )


class LegalAcceptance(Base):
    __tablename__ = "legal_acceptances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    legal_document_id = Column(Integer, ForeignKey("legal_documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_type = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ip_hash = Column(String, nullable=True)
    user_agent_summary = Column(String, nullable=True)
    acceptance_metadata = Column(JSON, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ux_legal_acceptances_user_document", "user_id", "legal_document_id", unique=True),
        Index("ix_legal_acceptances_user_type_version", "user_id", "document_type", "version"),
        Index("ix_legal_acceptances_user_accepted", "user_id", "accepted_at"),
    )


class BetaInviteCode(Base):
    __tablename__ = "beta_invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code_hash = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="active", index=True)
    max_uses = Column(Integer, nullable=False, default=1)
    use_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True, index=True)
    issued_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    email_restriction = Column(String, nullable=True, index=True)
    campaign = Column(String, nullable=True)
    source = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    invite_metadata = Column(JSON, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_beta_invite_codes_status_expires", "status", "expires_at"),
    )


class BetaInviteRedemption(Base):
    __tablename__ = "beta_invite_redemptions"

    id = Column(Integer, primary_key=True, index=True)
    invite_code_id = Column(Integer, ForeignKey("beta_invite_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email_at_redemption = Column(String, nullable=False, index=True)
    redeemed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    redemption_metadata = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ux_beta_invite_redemptions_user_invite", "user_id", "invite_code_id", unique=True),
        Index("ix_beta_invite_redemptions_invite_user", "invite_code_id", "user_id"),
    )


class UserBetaStatus(Base):
    __tablename__ = "user_beta_statuses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="active", index=True)
    source = Column(String, nullable=False, default="invite")
    invite_redemption_id = Column(Integer, ForeignKey("beta_invite_redemptions.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    status_metadata = Column(JSON, nullable=True)
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    suspended_at = Column(DateTime, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_user_beta_statuses_status_source", "status", "source"),
    )


class BetaWaitlistEntry(Base):
    __tablename__ = "beta_waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=True)
    use_case = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)
    waitlist_metadata = Column(JSON, nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_beta_waitlist_entries_status_created", "status", "created_at"),
    )


class PlatformIntegration(Base):
    __tablename__ = "platform_integrations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String, nullable=False)
    provider = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="active")
    integration_metadata = Column("metadata", JSON, nullable=True)
    credentials_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_platform_integrations_user_provider", "user_id", "provider"),
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    trading_mode = Column(String, nullable=False, default="paper")
    order_type = Column(String, nullable=False, default="market")
    limit_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    order_fingerprint = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="submitted", index=True)
    provider_order_id = Column(String, nullable=True, index=True)
    filled_quantity = Column(Integer, nullable=False, default=0)
    remaining_quantity = Column(Integer, nullable=False, default=0)
    rejected_reason = Column(Text, nullable=True)
    response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_paper_orders_user_idempotency", "user_id", "idempotency_key", unique=True),
        Index("ix_paper_orders_user_status", "user_id", "status"),
        Index("ix_paper_orders_user_fingerprint_created", "user_id", "order_fingerprint", "created_at"),
    )


class PaperOrderEvent(Base):
    __tablename__ = "paper_order_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    event_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=0)
    avg_price = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_paper_positions_scope", "user_id", "integration_id", "account_id", "symbol", unique=True),
    )


class PaperAccountSnapshot(Base):
    __tablename__ = "paper_account_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    cash_balance = Column(Float, nullable=False, default=100000.0)
    equity = Column(Float, nullable=False, default=100000.0)
    buying_power = Column(Float, nullable=False, default=100000.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    margin_used = Column(Float, nullable=False, default=0.0)
    last_mark_price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_paper_account_snapshots_scope", "user_id", "integration_id", "account_id"),
    )


class PaperLedgerEntry(Base):
    __tablename__ = "paper_ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    entry_type = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False, default=0.0)
    cash_balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    buying_power = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    description = Column(Text, nullable=True)
    entry_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_paper_ledger_entries_scope_created", "user_id", "integration_id", "account_id", "created_at"),
    )


class RiskSettings(Base):
    __tablename__ = "risk_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    trading_mode = Column(String, nullable=False, default="paper")
    enabled = Column(Integer, nullable=False, default=1)
    max_quantity = Column(Integer, nullable=False, default=1)
    max_contracts = Column(Integer, nullable=False, default=1)
    max_daily_loss = Column(Float, nullable=False, default=0.0)
    max_open_positions = Column(Integer, nullable=False, default=1)
    live_trading_enabled = Column(Integer, nullable=False, default=0)
    reset_policy = Column(String, nullable=False, default="daily")
    effective_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_risk_settings_scope", "user_id", "integration_id", "account_id", "trading_mode"),
    )


class DailyRiskState(Base):
    __tablename__ = "daily_risk_states"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    trading_mode = Column(String, nullable=False, default="paper")
    trading_day = Column(String, nullable=False, index=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    equity = Column(Float, nullable=True)
    buying_power = Column(Float, nullable=True)
    locked = Column(Integer, nullable=False, default=0)
    lock_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_daily_risk_states_scope_day", "user_id", "integration_id", "account_id", "trading_mode", "trading_day"),
    )


class KillSwitch(Base):
    __tablename__ = "kill_switches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    bot_session_id = Column(String, nullable=True, index=True)
    active = Column(Integer, nullable=False, default=1, index=True)
    reason = Column(Text, nullable=True)
    activated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deactivated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deactivated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_kill_switches_scope_active", "user_id", "integration_id", "account_id", "bot_session_id", "active"),
    )


class RiskLockoutEvent(Base):
    __tablename__ = "risk_lockout_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_settings_id = Column(Integer, ForeignKey("risk_settings.id", ondelete="SET NULL"), nullable=True)
    kill_switch_id = Column(Integer, ForeignKey("kill_switches.id", ondelete="SET NULL"), nullable=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    trading_mode = Column(String, nullable=False, default="paper")
    reason = Column(Text, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    cleared_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_risk_lockout_events_scope_active", "user_id", "integration_id", "account_id", "trading_mode", "active"),
    )


class RiskDecision(Base):
    __tablename__ = "risk_decisions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_settings_id = Column(Integer, ForeignKey("risk_settings.id", ondelete="SET NULL"), nullable=True)
    kill_switch_id = Column(Integer, ForeignKey("kill_switches.id", ondelete="SET NULL"), nullable=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=True, index=True)
    side = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    trading_mode = Column(String, nullable=False)
    source = Column(String, nullable=True)
    allowed = Column(Integer, nullable=False, default=0, index=True)
    reason_code = Column(String, nullable=False, index=True)
    reason = Column(Text, nullable=False)
    decision_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_risk_decisions_user_created", "user_id", "created_at"),
    )


class ProviderReconciliationRun(Base):
    __tablename__ = "provider_reconciliation_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=True, index=True)
    provider_order_id = Column(String, nullable=True, index=True)
    client_order_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    summary = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_provider_reconciliation_runs_scope", "user_id", "integration_id", "account_id", "status"),
    )


class ProviderReconciliationEvent(Base):
    __tablename__ = "provider_reconciliation_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("provider_reconciliation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    provider_status = Column(String, nullable=True)
    normalized_status = Column(String, nullable=True, index=True)
    message = Column(Text, nullable=False)
    provider_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProviderRetryDecision(Base):
    __tablename__ = "provider_retry_decisions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_order_id = Column(String, nullable=True, index=True)
    client_order_id = Column(String, nullable=True, index=True)
    error_type = Column(String, nullable=False, index=True)
    retryable = Column(Integer, nullable=False, default=0)
    requires_reconciliation = Column(Integer, nullable=False, default=1)
    decision = Column(String, nullable=False, index=True)
    reason = Column(Text, nullable=False)
    decision_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccountReconciliationLock(Base):
    __tablename__ = "account_reconciliation_locks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    active = Column(Integer, nullable=False, default=1, index=True)
    reason = Column(Text, nullable=False)
    run_id = Column(Integer, ForeignKey("provider_reconciliation_runs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    cleared_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_account_reconciliation_locks_scope_active", "user_id", "integration_id", "account_id", "active"),
    )


class LiveReadinessAcknowledgement(Base):
    __tablename__ = "live_readiness_acknowledgements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=True, index=True)
    risk_settings_id = Column(Integer, ForeignKey("risk_settings.id", ondelete="SET NULL"), nullable=True)
    acknowledgement_version = Column(String, nullable=False, default="live-readiness-v1")
    terms_version = Column(String, nullable=False, default="terms-v1")
    acknowledgement_type = Column(String, nullable=False, default="live_risk")
    accepted = Column(Integer, nullable=False, default=1)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)
    acknowledgement_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_live_readiness_ack_scope", "user_id", "integration_id", "account_id", "symbol", "accepted"),
    )


class LaunchGateEvaluation(Base):
    __tablename__ = "launch_gate_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    account_id = Column(String, nullable=True)
    symbol = Column(String, nullable=True, index=True)
    all_required_gates_passed = Column(Integer, nullable=False, default=0, index=True)
    live_trading_available = Column(Integer, nullable=False, default=0, index=True)
    live_feature_flag_enabled = Column(Integer, nullable=False, default=0)
    gate_results = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_launch_gate_evaluations_user_created", "user_id", "created_at"),
    )


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False, index=True)
    trading_mode = Column(String, nullable=False, default="paper")
    strategy_name = Column(String, nullable=False, default="rsi-threshold-v1")
    strategy_version = Column(String, nullable=False, default="1.0.0")
    parameters = Column(JSON, nullable=False)
    bot_session_id = Column(String, nullable=True, index=True)
    enabled = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_strategy_configs_user_symbol", "user_id", "symbol"),
    )


class StrategySignal(Base):
    __tablename__ = "strategy_signals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_config_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False, index=True)
    signal = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    reason = Column(Text, nullable=True)
    guardrail_decision = Column(JSON, nullable=True)
    market_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_strategy_signals_user_config", "user_id", "strategy_config_id"),
        Index("ix_strategy_signals_user_created", "user_id", "created_at"),
    )


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserPublic(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    email_verified_at: Optional[datetime] = None
    display_name: Optional[str] = None
    timezone: Optional[str] = None
    preferred_contact_email: Optional[str] = None
    trading_experience_level: Optional[str] = None

    class Config:
        from_attributes = True


class TradingRuleUpdate(BaseModel):
    buy_threshold: int
    sell_threshold: int


class IntegrationBase(BaseModel):
    display_name: str
    provider: IntegrationProvider
    metadata: Optional[dict[str, Any]] = None
    status: Optional[str] = "active"


class IntegrationCreate(IntegrationBase):
    credentials: Optional[dict[str, Any]] = None


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    credentials: Optional[dict[str, Any]] = None


class IntegrationOut(BaseModel):
    id: int
    display_name: str
    provider: IntegrationProvider
    status: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    has_credentials: bool

    class Config:
        orm_mode = True
