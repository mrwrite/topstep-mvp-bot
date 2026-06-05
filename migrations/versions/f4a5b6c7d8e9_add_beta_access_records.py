"""Add beta access records

Revision ID: f4a5b6c7d8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_admin", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "beta_invite_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("issued_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email_restriction", sa.String(), nullable=True),
        sa.Column("campaign", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("invite_metadata", sa.JSON(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_beta_invite_codes_id", "beta_invite_codes", ["id"])
    op.create_index("ix_beta_invite_codes_code_hash", "beta_invite_codes", ["code_hash"], unique=True)
    op.create_index("ix_beta_invite_codes_status", "beta_invite_codes", ["status"])
    op.create_index("ix_beta_invite_codes_expires_at", "beta_invite_codes", ["expires_at"])
    op.create_index("ix_beta_invite_codes_issued_by_user_id", "beta_invite_codes", ["issued_by_user_id"])
    op.create_index("ix_beta_invite_codes_email_restriction", "beta_invite_codes", ["email_restriction"])
    op.create_index("ix_beta_invite_codes_status_expires", "beta_invite_codes", ["status", "expires_at"])

    op.create_table(
        "beta_invite_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invite_code_id", sa.Integer(), sa.ForeignKey("beta_invite_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_at_redemption", sa.String(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=False),
        sa.Column("redemption_metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_beta_invite_redemptions_id", "beta_invite_redemptions", ["id"])
    op.create_index("ix_beta_invite_redemptions_invite_code_id", "beta_invite_redemptions", ["invite_code_id"])
    op.create_index("ix_beta_invite_redemptions_user_id", "beta_invite_redemptions", ["user_id"])
    op.create_index("ix_beta_invite_redemptions_email_at_redemption", "beta_invite_redemptions", ["email_at_redemption"])
    op.create_index(
        "ux_beta_invite_redemptions_user_invite",
        "beta_invite_redemptions",
        ["user_id", "invite_code_id"],
        unique=True,
    )
    op.create_index(
        "ix_beta_invite_redemptions_invite_user",
        "beta_invite_redemptions",
        ["invite_code_id", "user_id"],
    )

    op.create_table(
        "user_beta_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("source", sa.String(), nullable=False, server_default="invite"),
        sa.Column("invite_redemption_id", sa.Integer(), sa.ForeignKey("beta_invite_redemptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status_metadata", sa.JSON(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("exited_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_beta_statuses_id", "user_beta_statuses", ["id"])
    op.create_index("ix_user_beta_statuses_user_id", "user_beta_statuses", ["user_id"], unique=True)
    op.create_index("ix_user_beta_statuses_status", "user_beta_statuses", ["status"])
    op.create_index("ix_user_beta_statuses_status_source", "user_beta_statuses", ["status", "source"])

    op.create_table(
        "beta_waitlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("use_case", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("waitlist_metadata", sa.JSON(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_beta_waitlist_entries_id", "beta_waitlist_entries", ["id"])
    op.create_index("ix_beta_waitlist_entries_email", "beta_waitlist_entries", ["email"], unique=True)
    op.create_index("ix_beta_waitlist_entries_user_id", "beta_waitlist_entries", ["user_id"])
    op.create_index("ix_beta_waitlist_entries_status", "beta_waitlist_entries", ["status"])
    op.create_index("ix_beta_waitlist_entries_status_created", "beta_waitlist_entries", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_beta_waitlist_entries_status_created", table_name="beta_waitlist_entries")
    op.drop_index("ix_beta_waitlist_entries_status", table_name="beta_waitlist_entries")
    op.drop_index("ix_beta_waitlist_entries_user_id", table_name="beta_waitlist_entries")
    op.drop_index("ix_beta_waitlist_entries_email", table_name="beta_waitlist_entries")
    op.drop_index("ix_beta_waitlist_entries_id", table_name="beta_waitlist_entries")
    op.drop_table("beta_waitlist_entries")

    op.drop_index("ix_user_beta_statuses_status_source", table_name="user_beta_statuses")
    op.drop_index("ix_user_beta_statuses_status", table_name="user_beta_statuses")
    op.drop_index("ix_user_beta_statuses_user_id", table_name="user_beta_statuses")
    op.drop_index("ix_user_beta_statuses_id", table_name="user_beta_statuses")
    op.drop_table("user_beta_statuses")

    op.drop_index("ix_beta_invite_redemptions_invite_user", table_name="beta_invite_redemptions")
    op.drop_index("ux_beta_invite_redemptions_user_invite", table_name="beta_invite_redemptions")
    op.drop_index("ix_beta_invite_redemptions_email_at_redemption", table_name="beta_invite_redemptions")
    op.drop_index("ix_beta_invite_redemptions_user_id", table_name="beta_invite_redemptions")
    op.drop_index("ix_beta_invite_redemptions_invite_code_id", table_name="beta_invite_redemptions")
    op.drop_index("ix_beta_invite_redemptions_id", table_name="beta_invite_redemptions")
    op.drop_table("beta_invite_redemptions")

    op.drop_index("ix_beta_invite_codes_status_expires", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_email_restriction", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_issued_by_user_id", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_expires_at", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_status", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_code_hash", table_name="beta_invite_codes")
    op.drop_index("ix_beta_invite_codes_id", table_name="beta_invite_codes")
    op.drop_table("beta_invite_codes")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")
