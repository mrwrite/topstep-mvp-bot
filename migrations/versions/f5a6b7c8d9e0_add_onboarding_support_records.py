"""Add onboarding and support records

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "onboarding_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestones", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_onboarding_progress_id", "onboarding_progress", ["id"])
    op.create_index("ix_onboarding_progress_user_id", "onboarding_progress", ["user_id"], unique=True)

    op.create_table(
        "support_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("sanitized_message", sa.Text(), nullable=False),
        sa.Column("integration_id", sa.Integer(), sa.ForeignKey("platform_integrations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), sa.ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bot_session_id", sa.String(), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_support_requests_id", "support_requests", ["id"])
    op.create_index("ix_support_requests_user_id", "support_requests", ["user_id"])
    op.create_index("ix_support_requests_reference_id", "support_requests", ["reference_id"], unique=True)
    op.create_index("ix_support_requests_category", "support_requests", ["category"])
    op.create_index("ix_support_requests_severity", "support_requests", ["severity"])
    op.create_index("ix_support_requests_status", "support_requests", ["status"])
    op.create_index("ix_support_requests_bot_session_id", "support_requests", ["bot_session_id"])
    op.create_index("ix_support_requests_user_created", "support_requests", ["user_id", "created_at"])
    op.create_index("ix_support_requests_status_severity", "support_requests", ["status", "severity"])


def downgrade() -> None:
    op.drop_index("ix_support_requests_status_severity", table_name="support_requests")
    op.drop_index("ix_support_requests_user_created", table_name="support_requests")
    op.drop_index("ix_support_requests_bot_session_id", table_name="support_requests")
    op.drop_index("ix_support_requests_status", table_name="support_requests")
    op.drop_index("ix_support_requests_severity", table_name="support_requests")
    op.drop_index("ix_support_requests_category", table_name="support_requests")
    op.drop_index("ix_support_requests_reference_id", table_name="support_requests")
    op.drop_index("ix_support_requests_user_id", table_name="support_requests")
    op.drop_index("ix_support_requests_id", table_name="support_requests")
    op.drop_table("support_requests")

    op.drop_index("ix_onboarding_progress_user_id", table_name="onboarding_progress")
    op.drop_index("ix_onboarding_progress_id", table_name="onboarding_progress")
    op.drop_table("onboarding_progress")
