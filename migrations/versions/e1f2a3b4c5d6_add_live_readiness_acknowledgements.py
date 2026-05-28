"""Add live readiness acknowledgements and launch gates

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_readiness_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("risk_settings_id", sa.Integer(), nullable=True),
        sa.Column("acknowledgement_version", sa.String(), nullable=False),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column("acknowledgement_type", sa.String(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledgement_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["risk_settings_id"], ["risk_settings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_live_readiness_acknowledgements_id"), "live_readiness_acknowledgements", ["id"], unique=False)
    op.create_index(op.f("ix_live_readiness_acknowledgements_user_id"), "live_readiness_acknowledgements", ["user_id"], unique=False)
    op.create_index(op.f("ix_live_readiness_acknowledgements_symbol"), "live_readiness_acknowledgements", ["symbol"], unique=False)
    op.create_index(
        "ix_live_readiness_ack_scope",
        "live_readiness_acknowledgements",
        ["user_id", "integration_id", "account_id", "symbol", "accepted"],
        unique=False,
    )

    op.create_table(
        "launch_gate_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("all_required_gates_passed", sa.Integer(), nullable=False),
        sa.Column("live_trading_available", sa.Integer(), nullable=False),
        sa.Column("live_feature_flag_enabled", sa.Integer(), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["platform_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_launch_gate_evaluations_id"), "launch_gate_evaluations", ["id"], unique=False)
    op.create_index(op.f("ix_launch_gate_evaluations_user_id"), "launch_gate_evaluations", ["user_id"], unique=False)
    op.create_index(op.f("ix_launch_gate_evaluations_symbol"), "launch_gate_evaluations", ["symbol"], unique=False)
    op.create_index(op.f("ix_launch_gate_evaluations_all_required_gates_passed"), "launch_gate_evaluations", ["all_required_gates_passed"], unique=False)
    op.create_index(op.f("ix_launch_gate_evaluations_live_trading_available"), "launch_gate_evaluations", ["live_trading_available"], unique=False)
    op.create_index("ix_launch_gate_evaluations_user_created", "launch_gate_evaluations", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_launch_gate_evaluations_user_created", table_name="launch_gate_evaluations")
    op.drop_index(op.f("ix_launch_gate_evaluations_live_trading_available"), table_name="launch_gate_evaluations")
    op.drop_index(op.f("ix_launch_gate_evaluations_all_required_gates_passed"), table_name="launch_gate_evaluations")
    op.drop_index(op.f("ix_launch_gate_evaluations_symbol"), table_name="launch_gate_evaluations")
    op.drop_index(op.f("ix_launch_gate_evaluations_user_id"), table_name="launch_gate_evaluations")
    op.drop_index(op.f("ix_launch_gate_evaluations_id"), table_name="launch_gate_evaluations")
    op.drop_table("launch_gate_evaluations")

    op.drop_index("ix_live_readiness_ack_scope", table_name="live_readiness_acknowledgements")
    op.drop_index(op.f("ix_live_readiness_acknowledgements_symbol"), table_name="live_readiness_acknowledgements")
    op.drop_index(op.f("ix_live_readiness_acknowledgements_user_id"), table_name="live_readiness_acknowledgements")
    op.drop_index(op.f("ix_live_readiness_acknowledgements_id"), table_name="live_readiness_acknowledgements")
    op.drop_table("live_readiness_acknowledgements")
