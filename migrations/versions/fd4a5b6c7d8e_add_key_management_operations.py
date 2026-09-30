"""add durable key rotation and migration operations

Revision ID: fd4a5b6c7d8e
Revises: fc3f4a5b6c7d
"""

from alembic import op
import sqlalchemy as sa


revision = "fd4a5b6c7d8e"
down_revision = "fc3f4a5b6c7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("platform_integrations") as batch:
        batch.create_unique_constraint("uq_platform_integrations_user_id_id", ["user_id", "id"])
    op.create_table(
        "key_management_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("operation_type", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("target_version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="planned"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_key_management_operations_operation_type", "key_management_operations", ["operation_type"])
    op.create_index("ix_key_management_operations_state", "key_management_operations", ["state"])
    op.create_table(
        "key_management_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(), sa.ForeignKey("key_management_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.Column("result_hash", sa.String(), nullable=True),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "integration_id"],
                                ["platform_integrations.user_id", "platform_integrations.id"],
                                name="fk_key_management_item_tenant_integration", ondelete="CASCADE"),
        sa.UniqueConstraint("operation_id", "integration_id", name="uq_key_management_item_operation_record"),
    )
    op.create_index("ix_key_management_items_status", "key_management_items", ["status"])
    op.create_index("ix_key_management_items_claim_expires_at", "key_management_items", ["claim_expires_at"])
    op.create_index("ix_key_management_items_operation_status", "key_management_items", ["operation_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_key_management_items_operation_status", table_name="key_management_items")
    op.drop_index("ix_key_management_items_claim_expires_at", table_name="key_management_items")
    op.drop_index("ix_key_management_items_status", table_name="key_management_items")
    op.drop_table("key_management_items")
    op.drop_index("ix_key_management_operations_state", table_name="key_management_operations")
    op.drop_index("ix_key_management_operations_operation_type", table_name="key_management_operations")
    op.drop_table("key_management_operations")
    with op.batch_alter_table("platform_integrations") as batch:
        batch.drop_constraint("uq_platform_integrations_user_id_id", type_="unique")
