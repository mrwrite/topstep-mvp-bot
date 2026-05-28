"""Add strategy configs and signal records

Revision ID: a1b2c3d4e5f6
Revises: 8c2f7a1d9b44
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8c2f7a1d9b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("strategy_version", sa.String(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("bot_session_id", sa.String(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_configs_id"), "strategy_configs", ["id"], unique=False)
    op.create_index(op.f("ix_strategy_configs_user_id"), "strategy_configs", ["user_id"], unique=False)
    op.create_index(op.f("ix_strategy_configs_symbol"), "strategy_configs", ["symbol"], unique=False)
    op.create_index(op.f("ix_strategy_configs_bot_session_id"), "strategy_configs", ["bot_session_id"], unique=False)
    op.create_index("ix_strategy_configs_user_symbol", "strategy_configs", ["user_id", "symbol"], unique=False)

    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("strategy_config_id", sa.Integer(), nullable=False),
        sa.Column("paper_order_id", sa.Integer(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("guardrail_decision", sa.JSON(), nullable=True),
        sa.Column("market_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["strategy_config_id"], ["strategy_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_signals_id"), "strategy_signals", ["id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_user_id"), "strategy_signals", ["user_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_strategy_config_id"), "strategy_signals", ["strategy_config_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_paper_order_id"), "strategy_signals", ["paper_order_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_symbol"), "strategy_signals", ["symbol"], unique=False)
    op.create_index(op.f("ix_strategy_signals_status"), "strategy_signals", ["status"], unique=False)
    op.create_index("ix_strategy_signals_user_config", "strategy_signals", ["user_id", "strategy_config_id"], unique=False)
    op.create_index("ix_strategy_signals_user_created", "strategy_signals", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_strategy_signals_user_created", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_user_config", table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_status"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_symbol"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_paper_order_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_strategy_config_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_user_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_id"), table_name="strategy_signals")
    op.drop_table("strategy_signals")

    op.drop_index("ix_strategy_configs_user_symbol", table_name="strategy_configs")
    op.drop_index(op.f("ix_strategy_configs_bot_session_id"), table_name="strategy_configs")
    op.drop_index(op.f("ix_strategy_configs_symbol"), table_name="strategy_configs")
    op.drop_index(op.f("ix_strategy_configs_user_id"), table_name="strategy_configs")
    op.drop_index(op.f("ix_strategy_configs_id"), table_name="strategy_configs")
    op.drop_table("strategy_configs")
