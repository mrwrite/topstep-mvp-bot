"""Add subscription readiness records

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("billing_mode", sa.String(), nullable=False, server_default="disabled"),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default="usd"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("display_metadata", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plan_tiers_id", "plan_tiers", ["id"])
    op.create_index("ix_plan_tiers_code", "plan_tiers", ["code"], unique=True)
    op.create_index("ix_plan_tiers_status", "plan_tiers", ["status"])
    op.create_index("ix_plan_tiers_stripe_price_id", "plan_tiers", ["stripe_price_id"])
    op.create_index("ix_plan_tiers_sort_order", "plan_tiers", ["sort_order"])
    op.create_index("ix_plan_tiers_status_sort", "plan_tiers", ["status", "sort_order"])

    op.create_table(
        "user_subscription_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.String(), sa.ForeignKey("plan_tiers.code", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="beta"),
        sa.Column("billing_status", sa.String(), nullable=False, server_default="not_required"),
        sa.Column("source", sa.String(), nullable=False, server_default="beta_invite"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("subscription_metadata", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_subscription_statuses_id", "user_subscription_statuses", ["id"])
    op.create_index("ix_user_subscription_statuses_user_id", "user_subscription_statuses", ["user_id"], unique=True)
    op.create_index("ix_user_subscription_statuses_plan_code", "user_subscription_statuses", ["plan_code"])
    op.create_index("ix_user_subscription_statuses_status", "user_subscription_statuses", ["status"])
    op.create_index("ix_user_subscription_statuses_billing_status", "user_subscription_statuses", ["billing_status"])
    op.create_index("ix_user_subscription_statuses_stripe_customer_id", "user_subscription_statuses", ["stripe_customer_id"])
    op.create_index("ix_user_subscription_statuses_stripe_subscription_id", "user_subscription_statuses", ["stripe_subscription_id"])
    op.create_index("ix_user_subscription_statuses_plan_status", "user_subscription_statuses", ["plan_code", "status"])

    op.create_table(
        "user_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_code", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="subscription"),
        sa.Column("allowed", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("entitlement_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_entitlements_id", "user_entitlements", ["id"])
    op.create_index("ix_user_entitlements_user_id", "user_entitlements", ["user_id"])
    op.create_index("ix_user_entitlements_feature_code", "user_entitlements", ["feature_code"])
    op.create_index("ix_user_entitlements_source", "user_entitlements", ["source"])
    op.create_index("ix_user_entitlements_allowed", "user_entitlements", ["allowed"])
    op.create_index("ix_user_entitlements_expires_at", "user_entitlements", ["expires_at"])
    op.create_index("ux_user_entitlements_feature", "user_entitlements", ["user_id", "feature_code", "source"], unique=True)
    op.create_index("ix_user_entitlements_user_allowed", "user_entitlements", ["user_id", "allowed"])


def downgrade() -> None:
    op.drop_index("ix_user_entitlements_user_allowed", table_name="user_entitlements")
    op.drop_index("ux_user_entitlements_feature", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_expires_at", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_allowed", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_source", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_feature_code", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_user_id", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_id", table_name="user_entitlements")
    op.drop_table("user_entitlements")

    op.drop_index("ix_user_subscription_statuses_plan_status", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_stripe_subscription_id", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_stripe_customer_id", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_billing_status", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_status", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_plan_code", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_user_id", table_name="user_subscription_statuses")
    op.drop_index("ix_user_subscription_statuses_id", table_name="user_subscription_statuses")
    op.drop_table("user_subscription_statuses")

    op.drop_index("ix_plan_tiers_status_sort", table_name="plan_tiers")
    op.drop_index("ix_plan_tiers_sort_order", table_name="plan_tiers")
    op.drop_index("ix_plan_tiers_stripe_price_id", table_name="plan_tiers")
    op.drop_index("ix_plan_tiers_status", table_name="plan_tiers")
    op.drop_index("ix_plan_tiers_code", table_name="plan_tiers")
    op.drop_index("ix_plan_tiers_id", table_name="plan_tiers")
    op.drop_table("plan_tiers")
