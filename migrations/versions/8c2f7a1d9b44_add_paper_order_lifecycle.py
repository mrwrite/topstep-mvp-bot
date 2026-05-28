"""Add paper order lifecycle tables

Revision ID: 8c2f7a1d9b44
Revises: 4b6d0f9ac2f3
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c2f7a1d9b44"
down_revision: Union[str, Sequence[str], None] = "4b6d0f9ac2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("trading_mode", sa.String(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider_order_id", sa.String(), nullable=True),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_orders_id"), "paper_orders", ["id"], unique=False)
    op.create_index("ix_paper_orders_user_status", "paper_orders", ["user_id", "status"], unique=False)
    op.create_index(op.f("ix_paper_orders_user_id"), "paper_orders", ["user_id"], unique=False)
    op.create_index(op.f("ix_paper_orders_symbol"), "paper_orders", ["symbol"], unique=False)
    op.create_index(op.f("ix_paper_orders_status"), "paper_orders", ["status"], unique=False)
    op.create_index(op.f("ix_paper_orders_provider_order_id"), "paper_orders", ["provider_order_id"], unique=False)
    op.create_index("ux_paper_orders_user_idempotency", "paper_orders", ["user_id", "idempotency_key"], unique=True)

    op.create_table(
        "paper_order_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["paper_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_order_events_id"), "paper_order_events", ["id"], unique=False)
    op.create_index(op.f("ix_paper_order_events_order_id"), "paper_order_events", ["order_id"], unique=False)
    op.create_index(op.f("ix_paper_order_events_user_id"), "paper_order_events", ["user_id"], unique=False)

    op.create_table(
        "paper_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["paper_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_fills_id"), "paper_fills", ["id"], unique=False)
    op.create_index(op.f("ix_paper_fills_order_id"), "paper_fills", ["order_id"], unique=False)
    op.create_index(op.f("ix_paper_fills_user_id"), "paper_fills", ["user_id"], unique=False)
    op.create_index(op.f("ix_paper_fills_symbol"), "paper_fills", ["symbol"], unique=False)

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_positions_id"), "paper_positions", ["id"], unique=False)
    op.create_index(op.f("ix_paper_positions_user_id"), "paper_positions", ["user_id"], unique=False)
    op.create_index(op.f("ix_paper_positions_symbol"), "paper_positions", ["symbol"], unique=False)
    op.create_index(
        "ux_paper_positions_scope",
        "paper_positions",
        ["user_id", "integration_id", "account_id", "symbol"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_paper_positions_scope", table_name="paper_positions")
    op.drop_index(op.f("ix_paper_positions_symbol"), table_name="paper_positions")
    op.drop_index(op.f("ix_paper_positions_user_id"), table_name="paper_positions")
    op.drop_index(op.f("ix_paper_positions_id"), table_name="paper_positions")
    op.drop_table("paper_positions")

    op.drop_index(op.f("ix_paper_fills_symbol"), table_name="paper_fills")
    op.drop_index(op.f("ix_paper_fills_user_id"), table_name="paper_fills")
    op.drop_index(op.f("ix_paper_fills_order_id"), table_name="paper_fills")
    op.drop_index(op.f("ix_paper_fills_id"), table_name="paper_fills")
    op.drop_table("paper_fills")

    op.drop_index(op.f("ix_paper_order_events_user_id"), table_name="paper_order_events")
    op.drop_index(op.f("ix_paper_order_events_order_id"), table_name="paper_order_events")
    op.drop_index(op.f("ix_paper_order_events_id"), table_name="paper_order_events")
    op.drop_table("paper_order_events")

    op.drop_index("ux_paper_orders_user_idempotency", table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_provider_order_id"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_status"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_symbol"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_user_id"), table_name="paper_orders")
    op.drop_index("ix_paper_orders_user_status", table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_id"), table_name="paper_orders")
    op.drop_table("paper_orders")
