"""Add beta P0 session, audit, rate-limit, and account lifecycle records.

Revision ID: f8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""

from alembic import op
import sqlalchemy as sa

revision = "f8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("account_status", sa.String(), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_account_status", "users", ["account_status"])
    op.add_column("user_sessions", sa.Column("csrf_token_hash", sa.String(), nullable=True))

    op.create_table(
        "rate_limit_buckets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket_key", sa.String(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rate_limit_buckets_id", "rate_limit_buckets", ["id"])
    op.create_index("ix_rate_limit_buckets_bucket_key", "rate_limit_buckets", ["bucket_key"], unique=True)
    op.create_index("ix_rate_limit_buckets_window_started_at", "rate_limit_buckets", ["window_started_at"])

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("id", "actor_user_id", "target_user_id", "event_type", "case_id", "outcome", "created_at"):
        op.create_index(f"ix_security_audit_events_{column}", "security_audit_events", [column])

    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("execute_after", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("legal_hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("confirmation_hash", sa.String(), nullable=False),
        sa.Column("outcome_metadata", sa.JSON(), nullable=True),
    )
    for column in ("id", "user_id", "status"):
        op.create_index(f"ix_account_deletion_requests_{column}", "account_deletion_requests", [column])

    op.create_table(
        "provider_revocation_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "deletion_request_id",
            sa.Integer(),
            sa.ForeignKey("account_deletion_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("retryable", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provider_confirmed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
    )
    for column in ("id", "deletion_request_id", "integration_id", "outcome"):
        op.create_index(f"ix_provider_revocation_attempts_{column}", "provider_revocation_attempts", [column])


def downgrade() -> None:
    op.drop_table("provider_revocation_attempts")
    op.drop_table("account_deletion_requests")
    op.drop_table("security_audit_events")
    op.drop_table("rate_limit_buckets")
    op.drop_column("user_sessions", "csrf_token_hash")
    op.drop_index("ix_users_account_status", table_name="users")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "account_status")
