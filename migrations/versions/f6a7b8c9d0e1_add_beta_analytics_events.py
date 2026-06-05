"""Add beta analytics events

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_safe_id", sa.String(), nullable=True),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("event_category", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="beta-analytics-v1"),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="api"),
        sa.Column("provider", sa.String(), nullable=False, server_default="local"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_analytics_events_id", "analytics_events", ["id"])
    op.create_index("ix_analytics_events_user_id", "analytics_events", ["user_id"])
    op.create_index("ix_analytics_events_user_safe_id", "analytics_events", ["user_safe_id"])
    op.create_index("ix_analytics_events_event_name", "analytics_events", ["event_name"])
    op.create_index("ix_analytics_events_event_category", "analytics_events", ["event_category"])
    op.create_index("ix_analytics_events_environment", "analytics_events", ["environment"])
    op.create_index("ix_analytics_events_source", "analytics_events", ["source"])
    op.create_index("ix_analytics_events_created_at", "analytics_events", ["created_at"])
    op.create_index("ix_analytics_events_name_created", "analytics_events", ["event_name", "created_at"])
    op.create_index("ix_analytics_events_category_created", "analytics_events", ["event_category", "created_at"])
    op.create_index("ix_analytics_events_user_created", "analytics_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_analytics_events_user_created", table_name="analytics_events")
    op.drop_index("ix_analytics_events_category_created", table_name="analytics_events")
    op.drop_index("ix_analytics_events_name_created", table_name="analytics_events")
    op.drop_index("ix_analytics_events_created_at", table_name="analytics_events")
    op.drop_index("ix_analytics_events_source", table_name="analytics_events")
    op.drop_index("ix_analytics_events_environment", table_name="analytics_events")
    op.drop_index("ix_analytics_events_event_category", table_name="analytics_events")
    op.drop_index("ix_analytics_events_event_name", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_safe_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_id", table_name="analytics_events")
    op.drop_table("analytics_events")
