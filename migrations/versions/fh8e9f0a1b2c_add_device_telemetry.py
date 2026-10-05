"""add outbound-only local device telemetry

Revision ID: fh8e9f0a1b2c
Revises: fg7d8e9f0a1b
"""

from alembic import op
import sqlalchemy as sa


revision = "fh8e9f0a1b2c"
down_revision = "fg7d8e9f0a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_telemetry_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_hash", sa.String(64), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("credential_hash", name="uq_device_telemetry_credential_hash"),
        sa.UniqueConstraint("user_id", "installation_hash", name="uq_device_telemetry_installation"),
        sa.UniqueConstraint("user_id", "id", name="uq_device_telemetry_credential_tenant"),
        sa.CheckConstraint("active IN (0,1)", name="ck_device_telemetry_credential_active"),
    )
    op.create_index("ix_device_telemetry_credentials_user_id",
                    "device_telemetry_credentials", ["user_id"])
    op.create_table(
        "device_telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_hash", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "installation_hash", "event_id",
                            name="uq_device_telemetry_event_replay"),
        sa.CheckConstraint("schema_version > 0", name="ck_device_telemetry_schema"),
    )
    op.create_index("ix_device_telemetry_events_user_id", "device_telemetry_events", ["user_id"])
    op.create_index("ix_device_telemetry_tenant_received", "device_telemetry_events",
                    ["user_id", "received_at"])
    op.create_table(
        "device_telemetry_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_hash", sa.String(64), nullable=False),
        sa.Column("last_event_id", sa.String(36), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("software_version", sa.String(128), nullable=False),
        sa.Column("configuration_version", sa.String(128), nullable=False),
        sa.Column("health", sa.JSON(), nullable=False),
        sa.Column("lifecycle", sa.JSON(), nullable=False),
        sa.Column("latest_position", sa.JSON(), nullable=True),
        sa.Column("latest_fill", sa.JSON(), nullable=True),
        sa.Column("latest_pnl", sa.JSON(), nullable=True),
        sa.Column("latest_risk", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "installation_hash", name="uq_device_telemetry_projection"),
    )
    op.create_index("ix_device_telemetry_projections_user_id",
                    "device_telemetry_projections", ["user_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION reject_device_telemetry_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'device_telemetry_events_append_only'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("""
        CREATE TRIGGER device_telemetry_events_no_update_delete
        BEFORE UPDATE OR DELETE ON device_telemetry_events
        FOR EACH ROW EXECUTE FUNCTION reject_device_telemetry_event_mutation()
        """)
    else:
        op.execute(
            "CREATE TRIGGER device_telemetry_events_no_update BEFORE UPDATE ON device_telemetry_events "
            "BEGIN SELECT RAISE(ABORT, 'device_telemetry_events_append_only'); END"
        )
        op.execute(
            "CREATE TRIGGER device_telemetry_events_no_delete BEFORE DELETE ON device_telemetry_events "
            "BEGIN SELECT RAISE(ABORT, 'device_telemetry_events_append_only'); END"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS device_telemetry_events_no_update_delete "
                   "ON device_telemetry_events")
        op.execute("DROP FUNCTION IF EXISTS reject_device_telemetry_event_mutation")
    op.drop_index("ix_device_telemetry_projections_user_id",
                  table_name="device_telemetry_projections")
    op.drop_table("device_telemetry_projections")
    op.drop_index("ix_device_telemetry_tenant_received", table_name="device_telemetry_events")
    op.drop_index("ix_device_telemetry_events_user_id", table_name="device_telemetry_events")
    op.drop_table("device_telemetry_events")
    op.drop_index("ix_device_telemetry_credentials_user_id",
                  table_name="device_telemetry_credentials")
    op.drop_table("device_telemetry_credentials")
