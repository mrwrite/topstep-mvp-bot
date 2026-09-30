"""add hosted Trading Combine policy, consent, and read-only dry runs

Revision ID: fg7d8e9f0a1b
Revises: ff6c7d8e9f0a
"""

from alembic import op
import sqlalchemy as sa


revision = "fg7d8e9f0a1b"
down_revision = "ff6c7d8e9f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosted_restore_reconciliations") as batch:
        batch.add_column(sa.Column("dry_runs_suppressed", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "hosted_combine_risk_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cohort_id", sa.String(), nullable=False),
        sa.Column("tester_user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("required_consent_version", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_operator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operator_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id", "integration_id"],
                                ["platform_integrations.user_id", "platform_integrations.id"],
                                name="fk_hosted_policy_tenant_integration", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "id", name="uq_hosted_policy_user_id_id"),
        sa.UniqueConstraint("user_id", "integration_id", "policy_version", name="uq_hosted_policy_version"),
        sa.CheckConstraint("policy_version > 0 AND version > 0", name="ck_hosted_policy_version"),
        sa.CheckConstraint("state IN ('active','revoked','expired')", name="ck_hosted_policy_state"),
    )
    op.create_index("ix_hosted_policy_tenant_state", "hosted_combine_risk_policies",
                    ["user_id", "integration_id", "state"])
    op.create_index("ux_hosted_active_risk_policy", "hosted_combine_risk_policies",
                    ["user_id", "integration_id"], unique=True,
                    sqlite_where=sa.text("state = 'active'"), postgresql_where=sa.text("state = 'active'"))

    op.create_table(
        "hosted_combine_consents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("consent_version", sa.String(), nullable=False),
        sa.Column("consent_text", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id", "integration_id"],
                                ["platform_integrations.user_id", "platform_integrations.id"],
                                name="fk_hosted_consent_tenant_integration", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "id", name="uq_hosted_consent_user_id_id"),
    )
    op.create_index("ix_hosted_consent_binding", "hosted_combine_consents",
                    ["user_id", "integration_id", "credential_generation", "provider_account_id",
                     "policy_version", "accepted_at"])
    op.create_index("ux_hosted_current_consent", "hosted_combine_consents",
                    ["user_id", "integration_id", "credential_generation", "provider_account_id",
                     "approval_id", "policy_version", "consent_version"], unique=True,
                    sqlite_where=sa.text("revoked_at IS NULL"), postgresql_where=sa.text("revoked_at IS NULL"))

    op.create_table(
        "hosted_combine_dry_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("provider_account_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("security_epoch", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("consent_id", sa.String(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("strategy_version", sa.String(), nullable=False),
        sa.Column("configuration_hash", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("source_run_id", sa.String(), nullable=False),
        sa.Column("market_input_id", sa.String(), nullable=False),
        sa.Column("market_identity", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="requested"),
        sa.Column("result_classification", sa.String(), nullable=True),
        sa.Column("proposal_id", sa.String(), nullable=True),
        sa.Column("risk_results", sa.JSON(), nullable=True),
        sa.Column("failure_classification", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("stable_identity", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("causation_id", sa.String(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id", "integration_id"],
                                ["platform_integrations.user_id", "platform_integrations.id"],
                                name="fk_hosted_dryrun_tenant_integration", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id", "policy_id"],
                                ["hosted_combine_risk_policies.user_id", "hosted_combine_risk_policies.id"],
                                name="fk_hosted_dryrun_tenant_policy", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id", "consent_id"],
                                ["hosted_combine_consents.user_id", "hosted_combine_consents.id"],
                                name="fk_hosted_dryrun_tenant_consent", ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "id", name="uq_hosted_dryrun_user_id_id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_hosted_dryrun_idempotency"),
        sa.UniqueConstraint("user_id", "stable_identity", name="uq_hosted_dryrun_identity"),
        sa.CheckConstraint("fencing_token >= 0", name="ck_hosted_dryrun_fence"),
        sa.CheckConstraint("state IN ('requested','eligibility_checking','market_data_loading','evaluating',"
                           "'risk_evaluating','proposed','no_action','denied','degraded','failed','canceled','completed')",
                           name="ck_hosted_dryrun_state"),
    )
    op.create_index("ix_hosted_dryrun_queue", "hosted_combine_dry_runs", ["state", "requested_at"])
    op.create_index("ix_hosted_dryrun_tenant_integration", "hosted_combine_dry_runs",
                    ["user_id", "integration_id", "state"])

    op.create_table(
        "hosted_combine_proposals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dry_run_id", sa.String(), nullable=False),
        sa.Column("evaluation_identity", sa.String(), nullable=False),
        sa.Column("strategy_signal", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("risk_checks", sa.JSON(), nullable=False),
        sa.Column("data_freshness_seconds", sa.Integer(), nullable=False),
        sa.Column("schedule_allowed", sa.Integer(), nullable=False),
        sa.Column("position_snapshot_version", sa.String(), nullable=True),
        sa.Column("risk_snapshot_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="dry_run_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "id", name="uq_hosted_proposal_user_id_id"),
        sa.ForeignKeyConstraint(["user_id", "dry_run_id"],
                                ["hosted_combine_dry_runs.user_id", "hosted_combine_dry_runs.id"],
                                name="fk_hosted_proposal_tenant_dryrun", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "dry_run_id", name="uq_hosted_proposal_per_dryrun"),
        sa.CheckConstraint("quantity > 0", name="ck_hosted_proposal_quantity"),
        sa.CheckConstraint("status = 'dry_run_only'", name="ck_hosted_proposal_status"),
    )


def downgrade() -> None:
    op.drop_table("hosted_combine_proposals")
    op.drop_index("ix_hosted_dryrun_tenant_integration", table_name="hosted_combine_dry_runs")
    op.drop_index("ix_hosted_dryrun_queue", table_name="hosted_combine_dry_runs")
    op.drop_table("hosted_combine_dry_runs")
    op.drop_index("ux_hosted_current_consent", table_name="hosted_combine_consents")
    op.drop_index("ix_hosted_consent_binding", table_name="hosted_combine_consents")
    op.drop_table("hosted_combine_consents")
    op.drop_index("ux_hosted_active_risk_policy", table_name="hosted_combine_risk_policies")
    op.drop_index("ix_hosted_policy_tenant_state", table_name="hosted_combine_risk_policies")
    op.drop_table("hosted_combine_risk_policies")
    with op.batch_alter_table("hosted_restore_reconciliations") as batch:
        batch.drop_column("dry_runs_suppressed")
