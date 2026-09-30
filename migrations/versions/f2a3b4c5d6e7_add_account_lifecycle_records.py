"""Add account lifecycle records

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("display_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("timezone", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("preferred_contact_email", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("trading_experience_level", sa.String(), nullable=True))

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False, server_default="email_verification"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_email_verification_tokens_id", "email_verification_tokens", ["id"])
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])
    op.create_index("ix_email_verification_tokens_token_hash", "email_verification_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_verification_tokens_email", "email_verification_tokens", ["email"])
    op.create_index("ix_email_verification_tokens_expires_at", "email_verification_tokens", ["expires_at"])
    op.create_index(
        "ix_email_verification_tokens_user_consumed",
        "email_verification_tokens",
        ["user_id", "consumed_at"],
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_id", "password_reset_tokens", ["id"])
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    op.create_index("ix_password_reset_tokens_email", "password_reset_tokens", ["email"])
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    op.create_index(
        "ix_password_reset_tokens_user_consumed",
        "password_reset_tokens",
        ["user_id", "consumed_at"],
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_agent_summary", sa.String(), nullable=True),
        sa.Column("ip_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revocation_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_user_sessions_id", "user_sessions", ["id"])
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True)
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index("ix_user_sessions_user_revoked", "user_sessions", ["user_id", "revoked_at"])

    op.create_table(
        "account_recovery_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reference_id", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="account_recovery"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("sanitized_message", sa.Text(), nullable=False),
        sa.Column("request_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_recovery_requests_id", "account_recovery_requests", ["id"])
    op.create_index("ix_account_recovery_requests_user_id", "account_recovery_requests", ["user_id"])
    op.create_index("ix_account_recovery_requests_reference_id", "account_recovery_requests", ["reference_id"], unique=True)
    op.create_index("ix_account_recovery_requests_contact_email", "account_recovery_requests", ["contact_email"])
    op.create_index("ix_account_recovery_requests_status", "account_recovery_requests", ["status"])
    op.create_index(
        "ix_account_recovery_requests_user_status",
        "account_recovery_requests",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_recovery_requests_user_status", table_name="account_recovery_requests")
    op.drop_index("ix_account_recovery_requests_status", table_name="account_recovery_requests")
    op.drop_index("ix_account_recovery_requests_contact_email", table_name="account_recovery_requests")
    op.drop_index("ix_account_recovery_requests_reference_id", table_name="account_recovery_requests")
    op.drop_index("ix_account_recovery_requests_user_id", table_name="account_recovery_requests")
    op.drop_index("ix_account_recovery_requests_id", table_name="account_recovery_requests")
    op.drop_table("account_recovery_requests")

    op.drop_index("ix_user_sessions_user_revoked", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_session_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_password_reset_tokens_user_consumed", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_email", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_email_verification_tokens_user_consumed", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_expires_at", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_email", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_token_hash", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_user_id", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_tokens_id", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("trading_experience_level")
        batch_op.drop_column("preferred_contact_email")
        batch_op.drop_column("timezone")
        batch_op.drop_column("display_name")
        batch_op.drop_column("email_verified_at")
