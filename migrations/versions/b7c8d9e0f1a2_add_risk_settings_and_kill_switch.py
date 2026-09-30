"""Add risk settings and kill switch records

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("max_quantity", sa.Integer(), nullable=False),
        sa.Column("max_contracts", sa.Integer(), nullable=False),
        sa.Column("max_daily_loss", sa.Float(), nullable=False),
        sa.Column("max_open_positions", sa.Integer(), nullable=False),
        sa.Column("live_trading_enabled", sa.Integer(), nullable=False),
        sa.Column("reset_policy", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_settings_id"), "risk_settings", ["id"], unique=False)
    op.create_index(op.f("ix_risk_settings_user_id"), "risk_settings", ["user_id"], unique=False)
    op.create_index("ix_risk_settings_scope", "risk_settings", ["user_id", "integration_id", "account_id", "trading_mode"], unique=False)

    op.create_table(
        "daily_risk_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("trading_day", sa.String(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=True),
        sa.Column("buying_power", sa.Float(), nullable=True),
        sa.Column("locked", sa.Integer(), nullable=False),
        sa.Column("lock_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_daily_risk_states_id"), "daily_risk_states", ["id"], unique=False)
    op.create_index(op.f("ix_daily_risk_states_user_id"), "daily_risk_states", ["user_id"], unique=False)
    op.create_index(op.f("ix_daily_risk_states_trading_day"), "daily_risk_states", ["trading_day"], unique=False)
    op.create_index(
        "ix_daily_risk_states_scope_day",
        "daily_risk_states",
        ["user_id", "integration_id", "account_id", "trading_mode", "trading_day"],
        unique=False,
    )

    op.create_table(
        "kill_switches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("bot_session_id", sa.String(), nullable=True),
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("activated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("deactivated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deactivated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kill_switches_id"), "kill_switches", ["id"], unique=False)
    op.create_index(op.f("ix_kill_switches_user_id"), "kill_switches", ["user_id"], unique=False)
    op.create_index(op.f("ix_kill_switches_active"), "kill_switches", ["active"], unique=False)
    op.create_index(op.f("ix_kill_switches_bot_session_id"), "kill_switches", ["bot_session_id"], unique=False)
    op.create_index(
        "ix_kill_switches_scope_active",
        "kill_switches",
        ["user_id", "integration_id", "account_id", "bot_session_id", "active"],
        unique=False,
    )

    op.create_table(
        "risk_lockout_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("risk_settings_id", sa.Integer(), nullable=True),
        sa.Column("kill_switch_id", sa.Integer(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["kill_switch_id"], ["kill_switches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["risk_settings_id"], ["risk_settings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_lockout_events_id"), "risk_lockout_events", ["id"], unique=False)
    op.create_index(op.f("ix_risk_lockout_events_user_id"), "risk_lockout_events", ["user_id"], unique=False)
    op.create_index(
        "ix_risk_lockout_events_scope_active",
        "risk_lockout_events",
        ["user_id", "integration_id", "account_id", "trading_mode", "active"],
        unique=False,
    )

    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("risk_settings_id", sa.Integer(), nullable=True),
        sa.Column("kill_switch_id", sa.Integer(), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("allowed", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["kill_switch_id"], ["kill_switches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["risk_settings_id"], ["risk_settings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_decisions_id"), "risk_decisions", ["id"], unique=False)
    op.create_index(op.f("ix_risk_decisions_user_id"), "risk_decisions", ["user_id"], unique=False)
    op.create_index(op.f("ix_risk_decisions_paper_order_id"), "risk_decisions", ["paper_order_id"], unique=False)
    op.create_index(op.f("ix_risk_decisions_symbol"), "risk_decisions", ["symbol"], unique=False)
    op.create_index(op.f("ix_risk_decisions_allowed"), "risk_decisions", ["allowed"], unique=False)
    op.create_index(op.f("ix_risk_decisions_reason_code"), "risk_decisions", ["reason_code"], unique=False)
    op.create_index("ix_risk_decisions_user_created", "risk_decisions", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_risk_decisions_user_created", table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_reason_code"), table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_allowed"), table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_symbol"), table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_paper_order_id"), table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_user_id"), table_name="risk_decisions")
    op.drop_index(op.f("ix_risk_decisions_id"), table_name="risk_decisions")
    op.drop_table("risk_decisions")

    op.drop_index("ix_risk_lockout_events_scope_active", table_name="risk_lockout_events")
    op.drop_index(op.f("ix_risk_lockout_events_user_id"), table_name="risk_lockout_events")
    op.drop_index(op.f("ix_risk_lockout_events_id"), table_name="risk_lockout_events")
    op.drop_table("risk_lockout_events")

    op.drop_index("ix_kill_switches_scope_active", table_name="kill_switches")
    op.drop_index(op.f("ix_kill_switches_bot_session_id"), table_name="kill_switches")
    op.drop_index(op.f("ix_kill_switches_active"), table_name="kill_switches")
    op.drop_index(op.f("ix_kill_switches_user_id"), table_name="kill_switches")
    op.drop_index(op.f("ix_kill_switches_id"), table_name="kill_switches")
    op.drop_table("kill_switches")

    op.drop_index("ix_daily_risk_states_scope_day", table_name="daily_risk_states")
    op.drop_index(op.f("ix_daily_risk_states_trading_day"), table_name="daily_risk_states")
    op.drop_index(op.f("ix_daily_risk_states_user_id"), table_name="daily_risk_states")
    op.drop_index(op.f("ix_daily_risk_states_id"), table_name="daily_risk_states")
    op.drop_table("daily_risk_states")

    op.drop_index("ix_risk_settings_scope", table_name="risk_settings")
    op.drop_index(op.f("ix_risk_settings_user_id"), table_name="risk_settings")
    op.drop_index(op.f("ix_risk_settings_id"), table_name="risk_settings")
    op.drop_table("risk_settings")
