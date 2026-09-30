"""add durable Topstep onboarding, approval, and deletion records

Revision ID: fe5b6c7d8e9f
Revises: fd4a5b6c7d8e
"""

from alembic import op
import sqlalchemy as sa


revision = "fe5b6c7d8e9f"
down_revision = "fd4a5b6c7d8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("platform_integrations") as batch:
        batch.add_column(sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ux_topstep_active_integration", "platform_integrations", ["user_id"], unique=True,
                    postgresql_where=sa.text("lower(provider) = 'topstepx' AND status NOT IN ('deleted','inactive','disabled')"),
                    sqlite_where=sa.text("lower(provider) = 'topstepx' AND status NOT IN ('deleted','inactive','disabled')"))
    op.create_table(
        "topstep_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="topstepx"),
        sa.Column("lifecycle_status", sa.String(), nullable=False, server_default="pending_validation"),
        sa.Column("username_encrypted", sa.Text(), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("credential_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("credential_fingerprint", sa.String(), nullable=False),
        sa.Column("encryption_key_version", sa.String(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("last_auth_succeeded_at", sa.DateTime(timezone=True)),
        sa.Column("last_auth_failed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_classification", sa.String()),
        sa.Column("replaced_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_credentials_tenant_integration", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "integration_id", "credential_generation", name="uq_topstep_credential_generation"),
        sa.UniqueConstraint("user_id", "id", name="uq_topstep_credentials_user_id_id"),
        sa.CheckConstraint("is_current IN (0, 1)", name="ck_topstep_credential_current"),
        sa.CheckConstraint("credential_generation > 0", name="ck_topstep_credential_generation"),
    )
    op.create_index("ux_topstep_current_credential", "topstep_credentials", ["user_id", "integration_id"], unique=True, postgresql_where=sa.text("is_current = 1"), sqlite_where=sa.text("is_current = 1"))
    op.create_index("ix_topstep_credentials_tenant_state", "topstep_credentials", ["user_id", "lifecycle_status"])

    op.create_table(
        "topstep_provider_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("token_encrypted", sa.Text()),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_sessions_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "credential_id"], ["topstep_credentials.user_id", "topstep_credentials.id"], name="fk_topstep_sessions_tenant_credential", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "integration_id", "credential_generation", name="uq_topstep_session_generation"),
    )
    op.create_index("ix_topstep_sessions_tenant_expiry", "topstep_provider_sessions", ["user_id", "expires_at"])

    op.create_table(
        "topstep_discovery_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("provider_correlation_id", sa.String()),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_response_hash", sa.String(), nullable=False),
        sa.Column("provider_status", sa.String(), nullable=False),
        sa.Column("is_current", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_snapshots_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "credential_id"], ["topstep_credentials.user_id", "topstep_credentials.id"], name="fk_topstep_snapshots_tenant_credential", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "id", name="uq_topstep_snapshots_user_id_id"),
        sa.CheckConstraint("is_current IN (0, 1)", name="ck_topstep_snapshot_current"),
    )
    op.create_index("ix_topstep_snapshots_tenant_generation", "topstep_discovery_snapshots", ["user_id", "integration_id", "credential_generation"])

    op.create_table(
        "topstep_discovered_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("safe_display_label", sa.String(), nullable=False),
        sa.Column("can_trade", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_visible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_accounts_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "snapshot_id"], ["topstep_discovery_snapshots.user_id", "topstep_discovery_snapshots.id"], name="fk_topstep_accounts_tenant_snapshot", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "snapshot_id", "provider_account_id", name="uq_topstep_account_snapshot_id"),
        sa.UniqueConstraint("user_id", "id", name="uq_topstep_accounts_user_id_id"),
    )
    op.create_index("ix_topstep_accounts_tenant_provider", "topstep_discovered_accounts", ["user_id", "integration_id", "provider_account_id"])

    op.create_table(
        "topstep_combine_attestations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("discovered_account_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("attestation_version", sa.String(), nullable=False),
        sa.Column("attestation_text", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_classification", sa.String()),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_attest_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "discovered_account_id"], ["topstep_discovered_accounts.user_id", "topstep_discovered_accounts.id"], name="fk_topstep_attest_tenant_account", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "id", name="uq_topstep_attestations_user_id_id"),
    )
    op.create_index("ix_topstep_attest_tenant_account", "topstep_combine_attestations", ["user_id", "integration_id", "provider_account_id"])

    op.create_table(
        "topstep_account_approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("discovered_account_id", sa.Integer(), nullable=False),
        sa.Column("attestation_id", sa.String(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="topstepx"),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("cohort", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="approved"),
        sa.Column("approving_operator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operator_context", sa.JSON(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("case_reference", sa.String(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoking_operator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revocation_classification", sa.String()),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_approval_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "discovered_account_id"], ["topstep_discovered_accounts.user_id", "topstep_discovered_accounts.id"], name="fk_topstep_approval_tenant_account", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "attestation_id"], ["topstep_combine_attestations.user_id", "topstep_combine_attestations.id"], name="fk_topstep_approval_tenant_attestation", ondelete="CASCADE"),
    )
    op.create_index("ux_topstep_active_approval", "topstep_account_approvals", ["user_id", "integration_id"], unique=True, postgresql_where=sa.text("state = 'approved' AND revoked_at IS NULL"), sqlite_where=sa.text("state = 'approved' AND revoked_at IS NULL"))
    op.create_index("ix_topstep_approval_tenant_account", "topstep_account_approvals", ["user_id", "provider_account_id", "state"])

    op.create_table(
        "topstep_integration_tombstones",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("identity_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="deleted"),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "integration_id"], ["platform_integrations.user_id", "platform_integrations.id"], name="fk_topstep_tombstone_tenant_integration", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "integration_id", name="uq_topstep_tombstone_integration"),
    )
    op.create_index("ix_topstep_tombstone_tenant_identity", "topstep_integration_tombstones", ["user_id", "identity_hash"])


def downgrade() -> None:
    op.drop_table("topstep_integration_tombstones")
    op.drop_table("topstep_account_approvals")
    op.drop_table("topstep_combine_attestations")
    op.drop_table("topstep_discovered_accounts")
    op.drop_table("topstep_discovery_snapshots")
    op.drop_table("topstep_provider_sessions")
    op.drop_table("topstep_credentials")
    op.drop_index("ux_topstep_active_integration", table_name="platform_integrations")
    with op.batch_alter_table("platform_integrations") as batch:
        batch.drop_column("lifecycle_version")
