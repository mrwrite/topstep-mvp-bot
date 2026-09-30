"""Extend durable simulation execution semantics.

Revision ID: fa1d2e3f4a5b
Revises: f9c0d1e2f3a4
"""
from alembic import op
import sqlalchemy as sa

revision = "fa1d2e3f4a5b"
down_revision = "f9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paper_orders") as batch:
        batch.add_column(sa.Column("simulation_run_id", sa.String(), sa.ForeignKey("simulation_runs.id", name="fk_paper_orders_simulation_run", ondelete="SET NULL")))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer()))
    op.create_index("ix_paper_orders_simulation_run_id", "paper_orders", ["simulation_run_id"])
    with op.batch_alter_table("paper_fills") as batch:
        batch.add_column(sa.Column("simulation_run_id", sa.String(), sa.ForeignKey("simulation_runs.id", name="fk_paper_fills_simulation_run", ondelete="SET NULL")))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer()))
        batch.add_column(sa.Column("execution_identity", sa.String()))
    op.create_index("ix_paper_fills_simulation_run_id", "paper_fills", ["simulation_run_id"])
    op.create_index("ix_paper_fills_execution_identity", "paper_fills", ["execution_identity"], unique=True)
    with op.batch_alter_table("paper_ledger_entries") as batch:
        batch.add_column(sa.Column("simulation_run_id", sa.String(), sa.ForeignKey("simulation_runs.id", name="fk_paper_ledger_simulation_run", ondelete="SET NULL")))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer()))
    op.create_index("ix_paper_ledger_entries_simulation_run_id", "paper_ledger_entries", ["simulation_run_id"])
    with op.batch_alter_table("simulation_runs") as batch:
      for column in (
        sa.Column("desired_state", sa.String(), nullable=False, server_default="running"),
        sa.Column("scope_key", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("active_scope_key", sa.String()),
        sa.Column("configuration_hash", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("strategy_version", sa.String(), nullable=False, server_default="rsi-threshold-v1"),
        sa.Column("environment", sa.String(), nullable=False, server_default="simulation"),
        sa.Column("strategy_config_id", sa.Integer(), sa.ForeignKey("strategy_configs.id", name="fk_simulation_runs_strategy_config", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("causation_id", sa.String()),
        sa.Column("kill_requested_at", sa.DateTime()),
        sa.Column("last_heartbeat_at", sa.DateTime()),
        sa.Column("last_checkpoint_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_summary", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime()), sa.Column("stopped_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
      ):
        batch.add_column(column)
    op.create_index("ix_simulation_runs_scope_key", "simulation_runs", ["scope_key"])
    op.create_index("ix_simulation_runs_active_scope_key", "simulation_runs", ["active_scope_key"], unique=True)
    op.create_index("ix_simulation_runs_correlation_id", "simulation_runs", ["correlation_id"])

    with op.batch_alter_table("simulation_commands") as batch:
      for column in (
        sa.Column("correlation_id", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("causation_id", sa.String()), sa.Column("failure_code", sa.String()),
      ):
        batch.add_column(column)
    op.create_index("ix_simulation_commands_correlation_id", "simulation_commands", ["correlation_id"])

    with op.batch_alter_table("simulation_checkpoints") as batch:
      for column in (
        sa.Column("market_data_id", sa.String()),
        sa.Column("configuration_hash", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("strategy_version", sa.String(), nullable=False, server_default="rsi-threshold-v1"),
      ):
        batch.add_column(column)

    with op.batch_alter_table("outbox_events") as batch:
      for column in (
        sa.Column("claim_owner", sa.String()), sa.Column("claim_expires_at", sa.DateTime()),
        sa.Column("correlation_id", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("causation_id", sa.String()),
      ):
        batch.add_column(column)
    op.create_index("ix_outbox_events_claim_expires_at", "outbox_events", ["claim_expires_at"])
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])
    with op.batch_alter_table("outbox_deliveries") as batch:
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("failure_code", sa.String()))


def downgrade() -> None:
    op.drop_column("paper_ledger_entries", "simulation_fencing_token")
    op.drop_column("paper_ledger_entries", "simulation_run_id")
    op.drop_column("paper_fills", "execution_identity")
    op.drop_column("paper_fills", "simulation_fencing_token")
    op.drop_column("paper_fills", "simulation_run_id")
    op.drop_column("paper_orders", "simulation_fencing_token")
    op.drop_column("paper_orders", "simulation_run_id")
    op.drop_column("outbox_deliveries", "failure_code")
    op.drop_column("outbox_deliveries", "attempt")
    for column in ("causation_id", "correlation_id", "claim_expires_at", "claim_owner"):
        op.drop_column("outbox_events", column)
    for column in ("strategy_version", "configuration_hash", "market_data_id"):
        op.drop_column("simulation_checkpoints", column)
    for column in ("failure_code", "causation_id", "correlation_id"):
        op.drop_column("simulation_commands", column)
    for column in (
        "completed_at", "stopped_at", "started_at", "retry_count", "failure_summary",
        "last_checkpoint_sequence", "last_heartbeat_at", "kill_requested_at", "causation_id",
        "correlation_id", "strategy_config_id", "environment", "strategy_version",
        "configuration_hash", "active_scope_key", "scope_key", "desired_state",
    ):
        op.drop_column("simulation_runs", column)
