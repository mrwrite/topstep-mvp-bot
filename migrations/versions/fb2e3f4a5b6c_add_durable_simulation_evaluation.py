"""add durable simulation evaluation and recovery records

Revision ID: fb2e3f4a5b6c
Revises: fa1d2e3f4a5b
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "fb2e3f4a5b6c"
down_revision = "fa1d2e3f4a5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("simulation_runs") as batch:
        batch.add_column(sa.Column("last_checkpoint_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("last_market_data_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_evaluation_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("data_freshness", sa.String(), nullable=False, server_default="unknown")
        )
        batch.add_column(sa.Column("degraded_reason", sa.String(), nullable=True))
    with op.batch_alter_table("simulation_checkpoints") as batch:
        batch.add_column(
            sa.Column("checkpoint_hash", sa.String(), nullable=False, server_default="legacy-unverified")
        )

    with op.batch_alter_table("paper_positions") as batch:
        batch.add_column(sa.Column(
            "simulation_run_id",
            sa.String(),
            sa.ForeignKey(
                "simulation_runs.id",
                name="fk_paper_positions_simulation_run",
                ondelete="SET NULL",
            ),
            nullable=True,
        ))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_index("ix_paper_positions_simulation_run_id", "paper_positions", ["simulation_run_id"])

    with op.batch_alter_table("paper_account_snapshots") as batch:
        batch.add_column(sa.Column(
            "simulation_run_id",
            sa.String(),
            sa.ForeignKey(
                "simulation_runs.id",
                name="fk_paper_snapshots_simulation_run",
                ondelete="SET NULL",
            ),
            nullable=True,
        ))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_index(
        "ix_paper_account_snapshots_simulation_run_id", "paper_account_snapshots", ["simulation_run_id"]
    )

    with op.batch_alter_table("paper_ledger_entries") as batch:
        batch.add_column(sa.Column("execution_identity", sa.String(), nullable=True))
    op.create_index(
        "ix_paper_ledger_entries_execution_identity",
        "paper_ledger_entries", ["execution_identity"], unique=True,
    )
    with op.batch_alter_table("risk_decisions") as batch:
        batch.add_column(sa.Column(
            "simulation_run_id",
            sa.String(),
            sa.ForeignKey(
                "simulation_runs.id",
                name="fk_risk_decisions_simulation_run",
                ondelete="SET NULL",
            ),
            nullable=True,
        ))
        batch.add_column(sa.Column("simulation_fencing_token", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("evaluation_identity", sa.String(), nullable=True))
    op.create_index("ix_risk_decisions_simulation_run_id", "risk_decisions", ["simulation_run_id"])
    op.create_index(
        "ix_risk_decisions_evaluation_identity", "risk_decisions", ["evaluation_identity"], unique=True
    )

    op.create_table(
        "simulation_market_inputs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_sequence", sa.String(), nullable=True),
        sa.Column("source_identity", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("freshness", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("processing_owner", sa.String(), nullable=True),
        sa.Column("processing_fence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "source_identity", name="ux_simulation_market_source_identity"),
    )
    op.create_index("ix_simulation_market_inputs_run_id", "simulation_market_inputs", ["run_id"])
    op.create_index("ix_simulation_market_inputs_user_id", "simulation_market_inputs", ["user_id"])
    op.create_index("ix_simulation_market_inputs_event_at", "simulation_market_inputs", ["event_at"])
    op.create_index("ix_simulation_market_inputs_status", "simulation_market_inputs", ["status"])
    op.create_index(
        "ix_simulation_market_pending", "simulation_market_inputs", ["status", "created_at"]
    )

    op.create_table(
        "simulation_evaluations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "market_input_id", sa.String(),
            sa.ForeignKey("simulation_market_inputs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("evaluation_identity", sa.String(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("strategy_version", sa.String(), nullable=False),
        sa.Column("configuration_hash", sa.String(), nullable=False),
        sa.Column("lookback_identity", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("market_snapshot", sa.JSON(), nullable=False),
        sa.Column("freshness", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("causation_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "evaluation_identity", name="ux_simulation_evaluation_identity"),
    )
    op.create_index("ix_simulation_evaluations_run_id", "simulation_evaluations", ["run_id"])
    op.create_index("ix_simulation_evaluations_user_id", "simulation_evaluations", ["user_id"])
    op.create_index(
        "ix_simulation_evaluations_correlation_id", "simulation_evaluations", ["correlation_id"]
    )

    op.create_table(
        "simulation_risk_counters",
        sa.Column("run_id", sa.String(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees", sa.Float(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_execution_identity", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulation_risk_counters_user_id", "simulation_risk_counters", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_simulation_risk_counters_user_id", table_name="simulation_risk_counters")
    op.drop_table("simulation_risk_counters")
    op.drop_index("ix_simulation_evaluations_correlation_id", table_name="simulation_evaluations")
    op.drop_index("ix_simulation_evaluations_user_id", table_name="simulation_evaluations")
    op.drop_index("ix_simulation_evaluations_run_id", table_name="simulation_evaluations")
    op.drop_table("simulation_evaluations")
    op.drop_index("ix_simulation_market_pending", table_name="simulation_market_inputs")
    op.drop_index("ix_simulation_market_inputs_status", table_name="simulation_market_inputs")
    op.drop_index("ix_simulation_market_inputs_event_at", table_name="simulation_market_inputs")
    op.drop_index("ix_simulation_market_inputs_user_id", table_name="simulation_market_inputs")
    op.drop_index("ix_simulation_market_inputs_run_id", table_name="simulation_market_inputs")
    op.drop_table("simulation_market_inputs")
    op.drop_index("ix_risk_decisions_evaluation_identity", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_simulation_run_id", table_name="risk_decisions")
    op.drop_constraint("fk_risk_decisions_simulation_run", "risk_decisions", type_="foreignkey")
    op.drop_column("risk_decisions", "evaluation_identity")
    op.drop_column("risk_decisions", "simulation_fencing_token")
    op.drop_column("risk_decisions", "simulation_run_id")
    op.drop_index("ix_paper_ledger_entries_execution_identity", table_name="paper_ledger_entries")
    op.drop_column("paper_ledger_entries", "execution_identity")
    op.drop_index("ix_paper_account_snapshots_simulation_run_id", table_name="paper_account_snapshots")
    op.drop_constraint("fk_paper_snapshots_simulation_run", "paper_account_snapshots", type_="foreignkey")
    op.drop_column("paper_account_snapshots", "state_version")
    op.drop_column("paper_account_snapshots", "simulation_fencing_token")
    op.drop_column("paper_account_snapshots", "simulation_run_id")
    op.drop_index("ix_paper_positions_simulation_run_id", table_name="paper_positions")
    op.drop_constraint("fk_paper_positions_simulation_run", "paper_positions", type_="foreignkey")
    op.drop_column("paper_positions", "state_version")
    op.drop_column("paper_positions", "simulation_fencing_token")
    op.drop_column("paper_positions", "simulation_run_id")
    op.drop_column("simulation_checkpoints", "checkpoint_hash")
    op.drop_column("simulation_runs", "degraded_reason")
    op.drop_column("simulation_runs", "data_freshness")
    op.drop_column("simulation_runs", "last_evaluation_at")
    op.drop_column("simulation_runs", "last_market_data_at")
    op.drop_column("simulation_runs", "last_checkpoint_hash")
