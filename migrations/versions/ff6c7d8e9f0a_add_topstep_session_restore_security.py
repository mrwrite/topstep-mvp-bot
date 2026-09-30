"""add durable Topstep session renewal and hosted restore security epoch

Revision ID: ff6c7d8e9f0a
Revises: fe5b6c7d8e9f
"""

from alembic import op
import sqlalchemy as sa


revision = "ff6c7d8e9f0a"
down_revision = "fe5b6c7d8e9f"
branch_labels = None
depends_on = None


def _epoch_column():
    return sa.Column("security_epoch", sa.Integer(), nullable=False, server_default="1")


def upgrade() -> None:
    with op.batch_alter_table("platform_integrations") as batch:
        batch.add_column(_epoch_column())
        batch.add_column(sa.Column("onboarding_request_identity", sa.String(), nullable=True))
        batch.create_unique_constraint(
            "uq_topstep_onboarding_request_identity", ["user_id", "onboarding_request_identity"]
        )
    for table in (
        "topstep_credentials", "topstep_discovery_snapshots", "topstep_combine_attestations",
        "topstep_account_approvals", "topstep_integration_tombstones",
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(_epoch_column())

    with op.batch_alter_table("topstep_provider_sessions") as batch:
        batch.add_column(_epoch_column())
        batch.add_column(sa.Column("state", sa.String(), nullable=False, server_default="valid"))
        batch.add_column(sa.Column("session_generation", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("renewal_not_before", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("renewal_lease_owner", sa.String(), nullable=True))
        batch.add_column(sa.Column("renewal_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("failure_classification", sa.String(), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE topstep_provider_sessions SET renewal_not_before = expires_at")
    with op.batch_alter_table("topstep_provider_sessions") as batch:
        batch.alter_column("renewal_not_before", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_index("ix_topstep_sessions_tenant_renewal", ["user_id", "state", "renewal_not_before"])
        batch.create_check_constraint("ck_topstep_session_generation", "session_generation > 0")
        batch.create_check_constraint("ck_topstep_session_fence", "fencing_token >= 0")
        batch.create_check_constraint(
            "ck_topstep_session_state",
            "state IN ('valid','renewal_due','renewing','validating','reauthenticating','expired','revoked','failed','deleted')",
        )

    with op.batch_alter_table("simulation_runs") as batch:
        batch.add_column(sa.Column("integration_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("credential_generation", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("security_epoch", sa.Integer(), nullable=True))
    for table in ("simulation_commands", "outbox_events"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("integration_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("credential_generation", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("security_epoch", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("stable_identity", sa.String(), nullable=True))

    op.create_table(
        "hosted_security_epochs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("database_epoch", sa.Integer(), nullable=False),
        sa.Column("target_epoch", sa.Integer(), nullable=True),
        sa.Column("reconciliation_state", sa.String(), nullable=False, server_default="ready"),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_classification", sa.String(), nullable=True),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_hosted_security_epoch_singleton"),
        sa.CheckConstraint("database_epoch > 0", name="ck_hosted_security_epoch_positive"),
    )
    op.execute(
        "INSERT INTO hosted_security_epochs "
        "(id, database_epoch, target_epoch, reconciliation_state, correlation_id, started_at, completed_at, "
        "failure_classification, lifecycle_version, updated_at) "
        "VALUES (1, 1, NULL, 'ready', NULL, NULL, NULL, NULL, 1, CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "hosted_restore_reconciliations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_epoch", sa.Integer(), nullable=False),
        sa.Column("target_epoch", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="started"),
        sa.Column("correlation_id", sa.String(), nullable=False, unique=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("integrations_suppressed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commands_suppressed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbox_suppressed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_classification", sa.String(), nullable=True),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("target_epoch > source_epoch", name="ck_restore_epoch_advances"),
    )


def downgrade() -> None:
    op.drop_table("hosted_restore_reconciliations")
    op.drop_table("hosted_security_epochs")
    for table in ("outbox_events", "simulation_commands"):
        with op.batch_alter_table(table) as batch:
            for column in ("stable_identity", "security_epoch", "credential_generation", "integration_id"):
                batch.drop_column(column)
    with op.batch_alter_table("simulation_runs") as batch:
        for column in ("security_epoch", "credential_generation", "integration_id"):
            batch.drop_column(column)
    with op.batch_alter_table("topstep_provider_sessions") as batch:
        batch.drop_constraint("ck_topstep_session_state", type_="check")
        batch.drop_index("ix_topstep_sessions_tenant_renewal")
        for column in (
            "lifecycle_version", "deleted_at", "failure_classification", "attempt_count", "fencing_token",
            "renewal_lease_expires_at", "renewal_lease_owner", "renewal_not_before", "session_generation",
            "state", "security_epoch",
        ):
            batch.drop_column(column)
    for table in (
        "topstep_integration_tombstones", "topstep_account_approvals", "topstep_combine_attestations",
        "topstep_discovery_snapshots", "topstep_credentials", "platform_integrations",
    ):
        with op.batch_alter_table(table) as batch:
            if table == "platform_integrations":
                batch.drop_constraint("uq_topstep_onboarding_request_identity", type_="unique")
                batch.drop_column("onboarding_request_identity")
            batch.drop_column("security_epoch")
