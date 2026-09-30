"""Add durable simulation, outbox, and deletion tombstone records.

Revision ID: f9c0d1e2f3a4
Revises: f8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa

revision = "f9c0d1e2f3a4"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("simulation_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="requested"),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbol", sa.String(), nullable=False), sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_simulation_runs_user_id", "simulation_runs", ["user_id"])
    op.create_index("ix_simulation_runs_state", "simulation_runs", ["state"])
    op.create_table("simulation_leases",
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False), sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False), sa.Column("renewed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    op.create_index("ix_simulation_leases_user_id", "simulation_leases", ["user_id"])
    op.create_index("ix_simulation_leases_expires_at", "simulation_leases", ["expires_at"])
    op.create_table("simulation_commands",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False), sa.Column("command", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"), sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime()))
    op.create_index("ix_simulation_commands_run_id", "simulation_commands", ["run_id"])
    op.create_index("ix_simulation_commands_user_id", "simulation_commands", ["user_id"])
    op.create_index("ux_simulation_commands_tenant_key", "simulation_commands", ["user_id", "idempotency_key"], unique=True)
    op.create_table("simulation_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_simulation_checkpoints_run_id", "simulation_checkpoints", ["run_id"])
    op.create_index("ix_simulation_checkpoints_user_id", "simulation_checkpoints", ["user_id"])
    op.create_index("ux_simulation_checkpoint_sequence", "simulation_checkpoints", ["run_id", "sequence"], unique=True)
    op.create_table("outbox_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False), sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), nullable=False), sa.Column("terminal_reason", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_outbox_events_user_id", "outbox_events", ["user_id"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_table("outbox_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consumer", sa.String(), nullable=False), sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False))
    op.create_index("ux_outbox_delivery_consumer", "outbox_deliveries", ["event_id", "consumer"], unique=True)
    op.create_table("deletion_tombstones",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("identity_hash", sa.String(), nullable=False), sa.Column("deletion_request_id", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False), sa.Column("purge_eligible_at", sa.DateTime(), nullable=False),
        sa.Column("legal_hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"))
    for column in ("user_id", "identity_hash", "deletion_request_id"):
        op.create_index(f"ix_deletion_tombstones_{column}", "deletion_tombstones", [column])


def downgrade() -> None:
    for table in ("deletion_tombstones", "outbox_deliveries", "outbox_events", "simulation_checkpoints",
                  "simulation_commands", "simulation_leases", "simulation_runs"):
        op.drop_table(table)
