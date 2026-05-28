"""Add paper ledger and order lifecycle depth

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("paper_orders") as batch:
        batch.add_column(sa.Column("limit_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("stop_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("order_fingerprint", sa.String(), nullable=True))
        batch.add_column(sa.Column("filled_quantity", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("remaining_quantity", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("rejected_reason", sa.Text(), nullable=True))
    with op.batch_alter_table("paper_positions") as batch:
        batch.add_column(sa.Column("avg_price", sa.Float(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_paper_orders_order_fingerprint"), "paper_orders", ["order_fingerprint"], unique=False)
    op.create_index(
        "ix_paper_orders_user_fingerprint_created",
        "paper_orders",
        ["user_id", "order_fingerprint", "created_at"],
        unique=False,
    )

    op.create_table(
        "paper_account_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("cash_balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("buying_power", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("margin_used", sa.Float(), nullable=False),
        sa.Column("last_mark_price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_account_snapshots_id"), "paper_account_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_paper_account_snapshots_user_id"), "paper_account_snapshots", ["user_id"], unique=False)
    op.create_index(
        "ix_paper_account_snapshots_scope",
        "paper_account_snapshots",
        ["user_id", "integration_id", "account_id"],
        unique=False,
    )

    op.create_table(
        "paper_ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), nullable=True),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("cash_balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("buying_power", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entry_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_ledger_entries_id"), "paper_ledger_entries", ["id"], unique=False)
    op.create_index(op.f("ix_paper_ledger_entries_user_id"), "paper_ledger_entries", ["user_id"], unique=False)
    op.create_index(op.f("ix_paper_ledger_entries_paper_order_id"), "paper_ledger_entries", ["paper_order_id"], unique=False)
    op.create_index(op.f("ix_paper_ledger_entries_entry_type"), "paper_ledger_entries", ["entry_type"], unique=False)
    op.create_index(
        "ix_paper_ledger_entries_scope_created",
        "paper_ledger_entries",
        ["user_id", "integration_id", "account_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_paper_ledger_entries_scope_created", table_name="paper_ledger_entries")
    op.drop_index(op.f("ix_paper_ledger_entries_entry_type"), table_name="paper_ledger_entries")
    op.drop_index(op.f("ix_paper_ledger_entries_paper_order_id"), table_name="paper_ledger_entries")
    op.drop_index(op.f("ix_paper_ledger_entries_user_id"), table_name="paper_ledger_entries")
    op.drop_index(op.f("ix_paper_ledger_entries_id"), table_name="paper_ledger_entries")
    op.drop_table("paper_ledger_entries")

    op.drop_index("ix_paper_account_snapshots_scope", table_name="paper_account_snapshots")
    op.drop_index(op.f("ix_paper_account_snapshots_user_id"), table_name="paper_account_snapshots")
    op.drop_index(op.f("ix_paper_account_snapshots_id"), table_name="paper_account_snapshots")
    op.drop_table("paper_account_snapshots")

    op.drop_index("ix_paper_orders_user_fingerprint_created", table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_order_fingerprint"), table_name="paper_orders")
    with op.batch_alter_table("paper_positions") as batch:
        batch.drop_column("avg_price")
    with op.batch_alter_table("paper_orders") as batch:
        batch.drop_column("rejected_reason")
        batch.drop_column("remaining_quantity")
        batch.drop_column("filled_quantity")
        batch.drop_column("order_fingerprint")
        batch.drop_column("stop_price")
        batch.drop_column("limit_price")
