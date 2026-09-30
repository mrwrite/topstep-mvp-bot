"""Add reconciliation and retry records

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_reconciliation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("provider_order_id", sa.String(), nullable=True),
        sa.Column("client_order_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provider_reconciliation_runs_id"), "provider_reconciliation_runs", ["id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_runs_user_id"), "provider_reconciliation_runs", ["user_id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_runs_symbol"), "provider_reconciliation_runs", ["symbol"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_runs_provider_order_id"), "provider_reconciliation_runs", ["provider_order_id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_runs_client_order_id"), "provider_reconciliation_runs", ["client_order_id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_runs_status"), "provider_reconciliation_runs", ["status"], unique=False)
    op.create_index(
        "ix_provider_reconciliation_runs_scope",
        "provider_reconciliation_runs",
        ["user_id", "integration_id", "account_id", "status"],
        unique=False,
    )

    op.create_table(
        "provider_reconciliation_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("provider_status", sa.String(), nullable=True),
        sa.Column("normalized_status", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("provider_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["provider_reconciliation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provider_reconciliation_events_id"), "provider_reconciliation_events", ["id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_events_run_id"), "provider_reconciliation_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_events_user_id"), "provider_reconciliation_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_events_event_type"), "provider_reconciliation_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_provider_reconciliation_events_normalized_status"), "provider_reconciliation_events", ["normalized_status"], unique=False)

    op.create_table(
        "provider_retry_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), nullable=True),
        sa.Column("provider_order_id", sa.String(), nullable=True),
        sa.Column("client_order_id", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("retryable", sa.Integer(), nullable=False),
        sa.Column("requires_reconciliation", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provider_retry_decisions_id"), "provider_retry_decisions", ["id"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_user_id"), "provider_retry_decisions", ["user_id"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_paper_order_id"), "provider_retry_decisions", ["paper_order_id"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_provider_order_id"), "provider_retry_decisions", ["provider_order_id"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_client_order_id"), "provider_retry_decisions", ["client_order_id"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_error_type"), "provider_retry_decisions", ["error_type"], unique=False)
    op.create_index(op.f("ix_provider_retry_decisions_decision"), "provider_retry_decisions", ["decision"], unique=False)

    op.create_table(
        "account_reconciliation_locks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["provider_reconciliation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_reconciliation_locks_id"), "account_reconciliation_locks", ["id"], unique=False)
    op.create_index(op.f("ix_account_reconciliation_locks_user_id"), "account_reconciliation_locks", ["user_id"], unique=False)
    op.create_index(op.f("ix_account_reconciliation_locks_active"), "account_reconciliation_locks", ["active"], unique=False)
    op.create_index(
        "ix_account_reconciliation_locks_scope_active",
        "account_reconciliation_locks",
        ["user_id", "integration_id", "account_id", "active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_account_reconciliation_locks_scope_active", table_name="account_reconciliation_locks")
    op.drop_index(op.f("ix_account_reconciliation_locks_active"), table_name="account_reconciliation_locks")
    op.drop_index(op.f("ix_account_reconciliation_locks_user_id"), table_name="account_reconciliation_locks")
    op.drop_index(op.f("ix_account_reconciliation_locks_id"), table_name="account_reconciliation_locks")
    op.drop_table("account_reconciliation_locks")

    op.drop_index(op.f("ix_provider_retry_decisions_decision"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_error_type"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_client_order_id"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_provider_order_id"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_paper_order_id"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_user_id"), table_name="provider_retry_decisions")
    op.drop_index(op.f("ix_provider_retry_decisions_id"), table_name="provider_retry_decisions")
    op.drop_table("provider_retry_decisions")

    op.drop_index(op.f("ix_provider_reconciliation_events_normalized_status"), table_name="provider_reconciliation_events")
    op.drop_index(op.f("ix_provider_reconciliation_events_event_type"), table_name="provider_reconciliation_events")
    op.drop_index(op.f("ix_provider_reconciliation_events_user_id"), table_name="provider_reconciliation_events")
    op.drop_index(op.f("ix_provider_reconciliation_events_run_id"), table_name="provider_reconciliation_events")
    op.drop_index(op.f("ix_provider_reconciliation_events_id"), table_name="provider_reconciliation_events")
    op.drop_table("provider_reconciliation_events")

    op.drop_index("ix_provider_reconciliation_runs_scope", table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_status"), table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_client_order_id"), table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_provider_order_id"), table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_symbol"), table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_user_id"), table_name="provider_reconciliation_runs")
    op.drop_index(op.f("ix_provider_reconciliation_runs_id"), table_name="provider_reconciliation_runs")
    op.drop_table("provider_reconciliation_runs")
