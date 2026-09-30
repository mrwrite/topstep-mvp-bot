from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text, Index, Float, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, text
from datetime import datetime
from .database import Base
from pydantic import BaseModel
from typing import Any, Optional
from .providers.types import IntegrationProvider
from .time_utils import utc_now

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
    account_status = Column(String, nullable=False, default="active", index=True)
    deleted_at = Column(DateTime, nullable=True)

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
    csrf_token_hash = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_user_sessions_user_revoked", "user_id", "revoked_at"),
    )


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"

    id = Column(Integer, primary_key=True, index=True)
    bucket_key = Column(String, nullable=False, unique=True, index=True)
    window_started_at = Column(DateTime, nullable=False, index=True)
    request_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SecurityAuditEvent(Base):
    """Append-only security and operator evidence; application code never updates rows."""

    __tablename__ = "security_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    case_id = Column(String, nullable=True, index=True)
    outcome = Column(String, nullable=False, index=True)
    event_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AccountDeletionRequest(Base):
    __tablename__ = "account_deletion_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    execute_after = Column(DateTime, nullable=False)
    executed_at = Column(DateTime, nullable=True)
    legal_hold = Column(Integer, nullable=False, default=0)
    retention_days = Column(Integer, nullable=False, default=30)
    confirmation_hash = Column(String, nullable=False)
    outcome_metadata = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_account_deletion_requests_user_id_id"),
    )


class ProviderRevocationAttempt(Base):
    __tablename__ = "provider_revocation_attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    deletion_request_id = Column(
        Integer, ForeignKey("account_deletion_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id = Column(Integer, nullable=True, index=True)
    provider = Column(String, nullable=False)
    outcome = Column(String, nullable=False, index=True)
    retryable = Column(Integer, nullable=False, default=1)
    provider_confirmed = Column(Integer, nullable=False, default=0)
    detail = Column(Text, nullable=True)
    attempted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "deletion_request_id"],
            ["account_deletion_requests.user_id", "account_deletion_requests.id"],
            name="fk_provider_revocations_user_request", ondelete="CASCADE",
        ),
        Index("ix_provider_revocation_attempts_user_request", "user_id", "deletion_request_id"),
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


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    milestones = Column(JSON, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_id = Column(String, nullable=False, unique=True, index=True)
    category = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, default="normal", index=True)
    status = Column(String, nullable=False, default="open", index=True)
    subject = Column(String, nullable=False)
    sanitized_message = Column(Text, nullable=False)
    integration_id = Column(Integer, ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True)
    paper_order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True)
    bot_session_id = Column(String, nullable=True, index=True)
    diagnostics = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_support_requests_user_created", "user_id", "created_at"),
        Index("ix_support_requests_status_severity", "status", "severity"),
    )


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_safe_id = Column(String, nullable=True, index=True)
    event_name = Column(String, nullable=False, index=True)
    event_category = Column(String, nullable=False, index=True)
    schema_version = Column(String, nullable=False, default="beta-analytics-v1")
    environment = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, default="api", index=True)
    provider = Column(String, nullable=False, default="local")
    event_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_analytics_events_name_created", "event_name", "created_at"),
        Index("ix_analytics_events_category_created", "event_category", "created_at"),
        Index("ix_analytics_events_user_created", "user_id", "created_at"),
    )


class PlanTier(Base):
    __tablename__ = "plan_tiers"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="active", index=True)
    billing_mode = Column(String, nullable=False, default="disabled")
    monthly_price_cents = Column(Integer, nullable=True)
    currency = Column(String, nullable=False, default="usd")
    stripe_price_id = Column(String, nullable=True, index=True)
    features = Column(JSON, nullable=False)
    display_metadata = Column(JSON, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_plan_tiers_status_sort", "status", "sort_order"),
    )


class UserSubscriptionStatus(Base):
    __tablename__ = "user_subscription_statuses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    plan_code = Column(String, ForeignKey("plan_tiers.code", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String, nullable=False, default="beta", index=True)
    billing_status = Column(String, nullable=False, default="not_required", index=True)
    source = Column(String, nullable=False, default="beta_invite")
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    subscription_metadata = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    current_period_end = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_user_subscription_statuses_plan_status", "plan_code", "status"),
    )


class UserEntitlement(Base):
    __tablename__ = "user_entitlements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_code = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, default="subscription", index=True)
    allowed = Column(Integer, nullable=False, default=1, index=True)
    reason = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    entitlement_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ux_user_entitlements_feature", "user_id", "feature_code", "source", unique=True),
        Index("ix_user_entitlements_user_allowed", "user_id", "allowed"),
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
    lifecycle_version = Column(Integer, nullable=False, default=1)
    security_epoch = Column(Integer, nullable=False, default=1)
    onboarding_request_identity = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_platform_integrations_user_id_id"),
        UniqueConstraint("user_id", "onboarding_request_identity", name="uq_topstep_onboarding_request_identity"),
        Index("ix_platform_integrations_user_provider", "user_id", "provider"),
        Index("ux_topstep_active_integration", "user_id", unique=True,
              sqlite_where=text("lower(provider) = 'topstepx' AND status NOT IN ('deleted','inactive','disabled')"),
              postgresql_where=text("lower(provider) = 'topstepx' AND status NOT IN ('deleted','inactive','disabled')")),
    )


class TopstepCredential(Base):
    __tablename__ = "topstep_credentials"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    provider = Column(String, nullable=False, default="topstepx")
    lifecycle_status = Column(String, nullable=False, default="pending_validation")
    username_encrypted = Column(Text, nullable=True)
    api_key_encrypted = Column(Text, nullable=True)
    credential_schema_version = Column(Integer, nullable=False, default=1)
    credential_fingerprint = Column(String, nullable=False)
    encryption_key_version = Column(String, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    last_auth_succeeded_at = Column(DateTime(timezone=True), nullable=True)
    last_auth_failed_at = Column(DateTime(timezone=True), nullable=True)
    failure_classification = Column(String, nullable=True)
    replaced_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_credentials_tenant_integration", ondelete="CASCADE"),
        UniqueConstraint("user_id", "integration_id", "credential_generation",
                         name="uq_topstep_credential_generation"),
        UniqueConstraint("user_id", "id", name="uq_topstep_credentials_user_id_id"),
        Index("ux_topstep_current_credential", "user_id", "integration_id", unique=True,
              sqlite_where=text("is_current = 1"), postgresql_where=text("is_current = 1")),
        Index("ix_topstep_credentials_tenant_state", "user_id", "lifecycle_status"),
        CheckConstraint("is_current IN (0, 1)", name="ck_topstep_credential_current"),
        CheckConstraint("credential_generation > 0", name="ck_topstep_credential_generation"),
    )


class TopstepProviderSession(Base):
    __tablename__ = "topstep_provider_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    credential_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    state = Column(String, nullable=False, default="valid")
    session_generation = Column(Integer, nullable=False, default=1)
    token_encrypted = Column(Text, nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    renewal_not_before = Column(DateTime(timezone=True), nullable=False)
    renewal_lease_owner = Column(String, nullable=True)
    renewal_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    fencing_token = Column(Integer, nullable=False, default=0)
    attempt_count = Column(Integer, nullable=False, default=0)
    failure_classification = Column(String, nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    lifecycle_version = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_sessions_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "credential_id"],
                             ["topstep_credentials.user_id", "topstep_credentials.id"],
                             name="fk_topstep_sessions_tenant_credential", ondelete="CASCADE"),
        UniqueConstraint("user_id", "integration_id", "credential_generation",
                         name="uq_topstep_session_generation"),
        Index("ix_topstep_sessions_tenant_expiry", "user_id", "expires_at"),
        Index("ix_topstep_sessions_tenant_renewal", "user_id", "state", "renewal_not_before"),
        CheckConstraint("session_generation > 0", name="ck_topstep_session_generation"),
        CheckConstraint("fencing_token >= 0", name="ck_topstep_session_fence"),
        CheckConstraint(
            "state IN ('valid','renewal_due','renewing','validating','reauthenticating','expired','revoked','failed','deleted')",
            name="ck_topstep_session_state",
        ),
    )


class TopstepDiscoverySnapshot(Base):
    __tablename__ = "topstep_discovery_snapshots"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    credential_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    provider_correlation_id = Column(String, nullable=True)
    discovered_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    safe_response_hash = Column(String, nullable=False)
    provider_status = Column(String, nullable=False)
    is_current = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_snapshots_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "credential_id"],
                             ["topstep_credentials.user_id", "topstep_credentials.id"],
                             name="fk_topstep_snapshots_tenant_credential", ondelete="CASCADE"),
        UniqueConstraint("user_id", "id", name="uq_topstep_snapshots_user_id_id"),
        Index("ix_topstep_snapshots_tenant_generation", "user_id", "integration_id",
              "credential_generation"),
        CheckConstraint("is_current IN (0, 1)", name="ck_topstep_snapshot_current"),
    )


class TopstepDiscoveredAccount(Base):
    __tablename__ = "topstep_discovered_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    snapshot_id = Column(String, nullable=False)
    provider_account_id = Column(String, nullable=False)
    safe_display_label = Column(String, nullable=False)
    can_trade = Column(Integer, nullable=False, default=0)
    is_visible = Column(Integer, nullable=False, default=0)
    is_active = Column(Integer, nullable=False, default=1)
    first_observed_at = Column(DateTime(timezone=True), nullable=False)
    last_observed_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_accounts_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "snapshot_id"],
                             ["topstep_discovery_snapshots.user_id", "topstep_discovery_snapshots.id"],
                             name="fk_topstep_accounts_tenant_snapshot", ondelete="CASCADE"),
        UniqueConstraint("user_id", "snapshot_id", "provider_account_id",
                         name="uq_topstep_account_snapshot_id"),
        UniqueConstraint("user_id", "id", name="uq_topstep_accounts_user_id_id"),
        Index("ix_topstep_accounts_tenant_provider", "user_id", "integration_id", "provider_account_id"),
    )


class TopstepCombineAttestation(Base):
    __tablename__ = "topstep_combine_attestations"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    discovered_account_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    provider_account_id = Column(String, nullable=False)
    attestation_version = Column(String, nullable=False)
    attestation_text = Column(Text, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    correlation_id = Column(String, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revocation_classification = Column(String, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_attest_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "discovered_account_id"],
                             ["topstep_discovered_accounts.user_id", "topstep_discovered_accounts.id"],
                             name="fk_topstep_attest_tenant_account", ondelete="CASCADE"),
        UniqueConstraint("user_id", "id", name="uq_topstep_attestations_user_id_id"),
        Index("ix_topstep_attest_tenant_account", "user_id", "integration_id", "provider_account_id"),
    )


class TopstepAccountApproval(Base):
    __tablename__ = "topstep_account_approvals"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    discovered_account_id = Column(Integer, nullable=False)
    attestation_id = Column(String, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    provider = Column(String, nullable=False, default="topstepx")
    provider_account_id = Column(String, nullable=False)
    cohort = Column(String, nullable=False)
    state = Column(String, nullable=False, default="approved")
    approving_operator_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    operator_context = Column(JSON, nullable=False)
    purpose = Column(Text, nullable=False)
    case_reference = Column(String, nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoking_operator_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    revocation_classification = Column(String, nullable=True)
    correlation_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_approval_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "discovered_account_id"],
                             ["topstep_discovered_accounts.user_id", "topstep_discovered_accounts.id"],
                             name="fk_topstep_approval_tenant_account", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "attestation_id"],
                             ["topstep_combine_attestations.user_id", "topstep_combine_attestations.id"],
                             name="fk_topstep_approval_tenant_attestation", ondelete="CASCADE"),
        Index("ux_topstep_active_approval", "user_id", "integration_id", unique=True,
              sqlite_where=text("state = 'approved' AND revoked_at IS NULL"),
              postgresql_where=text("state = 'approved' AND revoked_at IS NULL")),
        Index("ix_topstep_approval_tenant_account", "user_id", "provider_account_id", "state"),
    )


class TopstepIntegrationTombstone(Base):
    __tablename__ = "topstep_integration_tombstones"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False, default=1)
    identity_hash = Column(String, nullable=False)
    state = Column(String, nullable=False, default="deleted")
    correlation_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_topstep_tombstone_tenant_integration", ondelete="CASCADE"),
        UniqueConstraint("user_id", "integration_id", name="uq_topstep_tombstone_integration"),
        Index("ix_topstep_tombstone_tenant_identity", "user_id", "identity_hash"),
    )


class HostedSecurityEpoch(Base):
    __tablename__ = "hosted_security_epochs"
    id = Column(Integer, primary_key=True, default=1)
    database_epoch = Column(Integer, nullable=False)
    target_epoch = Column(Integer, nullable=True)
    reconciliation_state = Column(String, nullable=False, default="ready")
    correlation_id = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failure_classification = Column(String, nullable=True)
    lifecycle_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_hosted_security_epoch_singleton"),
        CheckConstraint("database_epoch > 0", name="ck_hosted_security_epoch_positive"),
    )


class HostedRestoreReconciliation(Base):
    __tablename__ = "hosted_restore_reconciliations"
    id = Column(String, primary_key=True)
    source_epoch = Column(Integer, nullable=False)
    target_epoch = Column(Integer, nullable=False)
    state = Column(String, nullable=False, default="started")
    correlation_id = Column(String, nullable=False, unique=True)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    integrations_suppressed = Column(Integer, nullable=False, default=0)
    commands_suppressed = Column(Integer, nullable=False, default=0)
    outbox_suppressed = Column(Integer, nullable=False, default=0)
    dry_runs_suppressed = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failure_classification = Column(String, nullable=True)
    lifecycle_version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("target_epoch > source_epoch", name="ck_restore_epoch_advances"),
    )


class HostedCombineRiskPolicy(Base):
    __tablename__ = "hosted_combine_risk_policies"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cohort_id = Column(String, nullable=False)
    tester_user_id = Column(Integer, nullable=False)
    integration_id = Column(Integer, nullable=False)
    provider_account_id = Column(String, nullable=False)
    policy_version = Column(Integer, nullable=False)
    state = Column(String, nullable=False, default="active")
    policy = Column(JSON, nullable=False)
    required_consent_version = Column(String, nullable=False)
    effective_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_operator_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    operator_context = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_hosted_policy_tenant_integration", ondelete="CASCADE"),
        UniqueConstraint("user_id", "integration_id", "policy_version", name="uq_hosted_policy_version"),
        UniqueConstraint("user_id", "id", name="uq_hosted_policy_user_id_id"),
        Index("ix_hosted_policy_tenant_state", "user_id", "integration_id", "state"),
        Index("ux_hosted_active_risk_policy", "user_id", "integration_id", unique=True,
              sqlite_where=text("state = 'active'"), postgresql_where=text("state = 'active'")),
        CheckConstraint("policy_version > 0 AND version > 0", name="ck_hosted_policy_version"),
        CheckConstraint("state IN ('active','revoked','expired')", name="ck_hosted_policy_state"),
    )


class HostedCombineConsent(Base):
    __tablename__ = "hosted_combine_consents"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    provider_account_id = Column(String, nullable=False)
    approval_id = Column(String, nullable=False)
    policy_version = Column(Integer, nullable=False)
    consent_version = Column(String, nullable=False)
    consent_text = Column(Text, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    correlation_id = Column(String, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_hosted_consent_tenant_integration", ondelete="CASCADE"),
        UniqueConstraint("user_id", "id", name="uq_hosted_consent_user_id_id"),
        Index("ix_hosted_consent_binding", "user_id", "integration_id", "credential_generation",
              "provider_account_id", "policy_version", "accepted_at"),
        Index("ux_hosted_current_consent", "user_id", "integration_id", "credential_generation",
              "provider_account_id", "approval_id", "policy_version", "consent_version", unique=True,
              sqlite_where=text("revoked_at IS NULL"), postgresql_where=text("revoked_at IS NULL")),
    )


class HostedCombineDryRun(Base):
    __tablename__ = "hosted_combine_dry_runs"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    credential_generation = Column(Integer, nullable=False)
    provider_account_id = Column(String, nullable=False)
    approval_id = Column(String, nullable=False)
    approval_version = Column(Integer, nullable=False)
    security_epoch = Column(Integer, nullable=False)
    policy_id = Column(String, nullable=False)
    policy_version = Column(Integer, nullable=False)
    consent_id = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    strategy_version = Column(String, nullable=False)
    configuration_hash = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    source_run_id = Column(String, nullable=False)
    market_input_id = Column(String, nullable=False)
    market_identity = Column(String, nullable=False)
    state = Column(String, nullable=False, default="requested", index=True)
    result_classification = Column(String, nullable=True)
    proposal_id = Column(String, nullable=True)
    risk_results = Column(JSON, nullable=True)
    failure_classification = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=False)
    stable_identity = Column(String, nullable=False)
    correlation_id = Column(String, nullable=False)
    causation_id = Column(String, nullable=True)
    lease_owner = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    fencing_token = Column(Integer, nullable=False, default=0)
    attempt_count = Column(Integer, nullable=False, default=0)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "integration_id"],
                             ["platform_integrations.user_id", "platform_integrations.id"],
                             name="fk_hosted_dryrun_tenant_integration", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "policy_id"],
                             ["hosted_combine_risk_policies.user_id", "hosted_combine_risk_policies.id"],
                             name="fk_hosted_dryrun_tenant_policy", ondelete="RESTRICT"),
        ForeignKeyConstraint(["user_id", "consent_id"],
                             ["hosted_combine_consents.user_id", "hosted_combine_consents.id"],
                             name="fk_hosted_dryrun_tenant_consent", ondelete="RESTRICT"),
        UniqueConstraint("user_id", "id", name="uq_hosted_dryrun_user_id_id"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_hosted_dryrun_idempotency"),
        UniqueConstraint("user_id", "stable_identity", name="uq_hosted_dryrun_identity"),
        Index("ix_hosted_dryrun_queue", "state", "requested_at"),
        Index("ix_hosted_dryrun_tenant_integration", "user_id", "integration_id", "state"),
        CheckConstraint("fencing_token >= 0", name="ck_hosted_dryrun_fence"),
        CheckConstraint("state IN ('requested','eligibility_checking','market_data_loading','evaluating',"
                        "'risk_evaluating','proposed','no_action','denied','degraded','failed','canceled','completed')",
                        name="ck_hosted_dryrun_state"),
    )


class HostedCombineProposal(Base):
    __tablename__ = "hosted_combine_proposals"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dry_run_id = Column(String, nullable=False)
    evaluation_identity = Column(String, nullable=False)
    strategy_signal = Column(String, nullable=False)
    rationale = Column(Text, nullable=False)
    instrument = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    order_type = Column(String, nullable=False)
    limit_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    policy_version = Column(Integer, nullable=False)
    risk_checks = Column(JSON, nullable=False)
    data_freshness_seconds = Column(Integer, nullable=False)
    schedule_allowed = Column(Integer, nullable=False)
    position_snapshot_version = Column(String, nullable=True)
    risk_snapshot_version = Column(String, nullable=True)
    status = Column(String, nullable=False, default="dry_run_only")
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_hosted_proposal_user_id_id"),
        ForeignKeyConstraint(["user_id", "dry_run_id"],
                             ["hosted_combine_dry_runs.user_id", "hosted_combine_dry_runs.id"],
                             name="fk_hosted_proposal_tenant_dryrun", ondelete="CASCADE"),
        UniqueConstraint("user_id", "dry_run_id", name="uq_hosted_proposal_per_dryrun"),
        CheckConstraint("quantity > 0", name="ck_hosted_proposal_quantity"),
        CheckConstraint("status = 'dry_run_only'", name="ck_hosted_proposal_status"),
    )


class KeyManagementOperation(Base):
    __tablename__ = "key_management_operations"

    id = Column(String, primary_key=True)
    operation_type = Column(String, nullable=False, index=True)
    source_version = Column(String, nullable=True)
    target_version = Column(String, nullable=False)
    state = Column(String, nullable=False, default="planned", index=True)
    total_count = Column(Integer, nullable=False, default=0)
    succeeded_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    operation_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class KeyManagementItem(Base):
    __tablename__ = "key_management_items"

    id = Column(Integer, primary_key=True)
    operation_id = Column(String, ForeignKey("key_management_operations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    integration_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    source_hash = Column(String, nullable=False)
    result_hash = Column(String, nullable=True)
    claimed_by = Column(String, nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    failure_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("operation_id", "integration_id", name="uq_key_management_item_operation_record"),
        ForeignKeyConstraint(
            ["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"],
            name="fk_key_management_item_tenant_integration", ondelete="CASCADE",
        ),
        Index("ix_key_management_items_operation_status", "operation_id", "status"),
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
    execution_identity = Column(String, nullable=True, unique=True, index=True)
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
    state_version = Column(Integer, nullable=False, default=0)
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
    state_version = Column(Integer, nullable=False, default=0)
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
    execution_identity = Column(String, nullable=True, unique=True, index=True)
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
    simulation_run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    simulation_fencing_token = Column(Integer, nullable=True)
    evaluation_identity = Column(String, nullable=True, unique=True, index=True)
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


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    state = Column(String, nullable=False, default="requested", index=True)
    state_version = Column(Integer, nullable=False, default=1)
    fencing_token = Column(Integer, nullable=False, default=0)
    desired_state = Column(String, nullable=False, default="running")
    scope_key = Column(String, nullable=False, index=True)
    active_scope_key = Column(String, nullable=True, unique=True, index=True)
    symbol = Column(String, nullable=False)
    configuration = Column(JSON, nullable=False)
    configuration_hash = Column(String, nullable=False)
    integration_id = Column(Integer, nullable=True)
    credential_generation = Column(Integer, nullable=True)
    security_epoch = Column(Integer, nullable=True)
    strategy_version = Column(String, nullable=False, default="rsi-threshold-v1")
    environment = Column(String, nullable=False, default="simulation")
    strategy_config_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True)
    correlation_id = Column(String, nullable=False, index=True)
    causation_id = Column(String, nullable=True)
    kill_requested_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    last_checkpoint_sequence = Column(Integer, nullable=False, default=0)
    last_checkpoint_hash = Column(String, nullable=True)
    last_market_data_at = Column(DateTime(timezone=True), nullable=True)
    last_evaluation_at = Column(DateTime(timezone=True), nullable=True)
    data_freshness = Column(String, nullable=False, default="unknown")
    degraded_reason = Column(String, nullable=True)
    failure_code = Column(String, nullable=True)
    failure_summary = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SimulationLease(Base):
    __tablename__ = "simulation_leases"
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(String, nullable=False)
    fencing_token = Column(Integer, nullable=False)
    acquired_at = Column(DateTime, nullable=False)
    renewed_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class SimulationCommand(Base):
    __tablename__ = "simulation_commands"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    command = Column(String, nullable=False)
    integration_id = Column(Integer, nullable=True)
    credential_generation = Column(Integer, nullable=True)
    security_epoch = Column(Integer, nullable=True)
    stable_identity = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    result = Column(JSON, nullable=True)
    correlation_id = Column(String, nullable=False, index=True)
    causation_id = Column(String, nullable=True)
    failure_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ux_simulation_commands_tenant_key", "user_id", "idempotency_key", unique=True),)


class SimulationCheckpoint(Base):
    __tablename__ = "simulation_checkpoints"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fencing_token = Column(Integer, nullable=False)
    sequence = Column(Integer, nullable=False)
    checkpoint = Column(JSON, nullable=False)
    market_data_id = Column(String, nullable=True)
    configuration_hash = Column(String, nullable=False)
    strategy_version = Column(String, nullable=False)
    checkpoint_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("ux_simulation_checkpoint_sequence", "run_id", "sequence", unique=True),)


class SimulationMarketInput(Base):
    __tablename__ = "simulation_market_inputs"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False, index=True)
    provider_sequence = Column(String, nullable=True)
    source_identity = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    freshness = Column(String, nullable=False, default="unknown")
    failure_code = Column(String, nullable=True)
    processing_owner = Column(String, nullable=True)
    processing_fence = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ux_simulation_market_source_identity", "run_id", "source_identity", unique=True),
        Index("ix_simulation_market_pending", "status", "created_at"),
    )


class SimulationEvaluation(Base):
    __tablename__ = "simulation_evaluations"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    market_input_id = Column(String, ForeignKey("simulation_market_inputs.id", ondelete="CASCADE"), nullable=False)
    evaluation_identity = Column(String, nullable=False)
    fencing_token = Column(Integer, nullable=False)
    strategy_name = Column(String, nullable=False)
    strategy_version = Column(String, nullable=False)
    configuration_hash = Column(String, nullable=False)
    lookback_identity = Column(String, nullable=False)
    signal = Column(String, nullable=False)
    status = Column(String, nullable=False)
    rationale = Column(Text, nullable=False)
    market_snapshot = Column(JSON, nullable=False)
    freshness = Column(String, nullable=False)
    correlation_id = Column(String, nullable=False, index=True)
    causation_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        Index("ux_simulation_evaluation_identity", "run_id", "evaluation_identity", unique=True),
    )


class SimulationRiskCounter(Base):
    __tablename__ = "simulation_risk_counters"
    run_id = Column(String, ForeignKey("simulation_runs.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trade_count = Column(Integer, nullable=False, default=0)
    consecutive_losses = Column(Integer, nullable=False, default=0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    fees = Column(Float, nullable=False, default=0.0)
    version = Column(Integer, nullable=False, default=0)
    last_execution_identity = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    integration_id = Column(Integer, nullable=True)
    credential_generation = Column(Integer, nullable=True)
    security_epoch = Column(Integer, nullable=True)
    stable_identity = Column(String, nullable=True)
    payload = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    terminal_reason = Column(String, nullable=True)
    claim_owner = Column(String, nullable=True)
    claim_expires_at = Column(DateTime, nullable=True, index=True)
    correlation_id = Column(String, nullable=False, index=True)
    causation_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_outbox_events_user_id_id"),
    )


class OutboxDelivery(Base):
    __tablename__ = "outbox_deliveries"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String, ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False)
    consumer = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    failure_code = Column(String, nullable=True)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        Index("ux_outbox_delivery_consumer", "event_id", "consumer", unique=True),
        Index("ix_outbox_deliveries_user_event", "user_id", "event_id"),
        ForeignKeyConstraint(
            ["user_id", "event_id"], ["outbox_events.user_id", "outbox_events.id"],
            name="fk_outbox_deliveries_user_event", ondelete="CASCADE",
        ),
    )


class DeletionTombstone(Base):
    __tablename__ = "deletion_tombstones"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    identity_hash = Column(String, nullable=False, index=True)
    deletion_request_id = Column(Integer, nullable=False, index=True)
    executed_at = Column(DateTime, nullable=False)
    purge_eligible_at = Column(DateTime, nullable=False)
    legal_hold = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="active")


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
