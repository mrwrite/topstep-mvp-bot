"""enforce tenant-owned delivery and revocation links

Revision ID: fc3f4a5b6c7d
Revises: fb2e3f4a5b6c
"""

from alembic import op
import sqlalchemy as sa


revision = "fc3f4a5b6c7d"
down_revision = "fb2e3f4a5b6c"
branch_labels = None
depends_on = None


def _assert_backfilled(table: str) -> None:
    connection = op.get_bind()
    missing = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")).scalar_one()
    if missing:
        raise RuntimeError(f"tenant_backfill_failed:{table}:{missing}")


def upgrade() -> None:
    with op.batch_alter_table("outbox_deliveries") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(sa.text(
        "UPDATE outbox_deliveries SET user_id = "
        "(SELECT user_id FROM outbox_events WHERE outbox_events.id = outbox_deliveries.event_id)"
    ))
    _assert_backfilled("outbox_deliveries")
    with op.batch_alter_table("outbox_events") as batch:
        batch.create_unique_constraint("uq_outbox_events_user_id_id", ["user_id", "id"])
    with op.batch_alter_table("outbox_deliveries") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.create_index("ix_outbox_deliveries_user_id", ["user_id"])
        batch.create_index("ix_outbox_deliveries_user_event", ["user_id", "event_id"])
        batch.create_foreign_key(
            "fk_outbox_deliveries_user_event",
            "outbox_events", ["user_id", "event_id"], ["user_id", "id"], ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_outbox_deliveries_user", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("provider_revocation_attempts") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(sa.text(
        "UPDATE provider_revocation_attempts SET user_id = "
        "(SELECT user_id FROM account_deletion_requests "
        "WHERE account_deletion_requests.id = provider_revocation_attempts.deletion_request_id)"
    ))
    _assert_backfilled("provider_revocation_attempts")
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.create_unique_constraint("uq_account_deletion_requests_user_id_id", ["user_id", "id"])
    with op.batch_alter_table("provider_revocation_attempts") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.create_index("ix_provider_revocation_attempts_user_id", ["user_id"])
        batch.create_index(
            "ix_provider_revocation_attempts_user_request", ["user_id", "deletion_request_id"]
        )
        batch.create_foreign_key(
            "fk_provider_revocations_user_request",
            "account_deletion_requests", ["user_id", "deletion_request_id"], ["user_id", "id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_provider_revocations_user", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    # Tenant-leading lookup indexes cover beta hot paths and make accidental
    # global scans visible in query plans without claiming PostgreSQL RLS.
    for table, columns, name in (
        ("simulation_runs", ["user_id", "id"], "ix_simulation_runs_user_id_id"),
        ("simulation_commands", ["user_id", "run_id", "status"], "ix_simulation_commands_user_run_status"),
        ("simulation_market_inputs", ["user_id", "run_id", "status"], "ix_simulation_market_user_run_status"),
        ("simulation_evaluations", ["user_id", "run_id", "created_at"], "ix_simulation_evaluations_user_run_created"),
        ("simulation_checkpoints", ["user_id", "run_id", "sequence"], "ix_simulation_checkpoints_user_run_sequence"),
        ("paper_orders", ["user_id", "id"], "ix_paper_orders_user_id_id"),
        ("paper_fills", ["user_id", "order_id"], "ix_paper_fills_user_order"),
        ("paper_ledger_entries", ["user_id", "paper_order_id"], "ix_paper_ledger_user_order"),
    ):
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for table, name in (
        ("paper_ledger_entries", "ix_paper_ledger_user_order"),
        ("paper_fills", "ix_paper_fills_user_order"),
        ("paper_orders", "ix_paper_orders_user_id_id"),
        ("simulation_checkpoints", "ix_simulation_checkpoints_user_run_sequence"),
        ("simulation_evaluations", "ix_simulation_evaluations_user_run_created"),
        ("simulation_market_inputs", "ix_simulation_market_user_run_status"),
        ("simulation_commands", "ix_simulation_commands_user_run_status"),
        ("simulation_runs", "ix_simulation_runs_user_id_id"),
    ):
        op.drop_index(name, table_name=table)
    with op.batch_alter_table("provider_revocation_attempts") as batch:
        batch.drop_constraint("fk_provider_revocations_user_request", type_="foreignkey")
        batch.drop_constraint("fk_provider_revocations_user", type_="foreignkey")
        batch.drop_index("ix_provider_revocation_attempts_user_request")
        batch.drop_index("ix_provider_revocation_attempts_user_id")
        batch.drop_column("user_id")
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.drop_constraint("uq_account_deletion_requests_user_id_id", type_="unique")
    with op.batch_alter_table("outbox_deliveries") as batch:
        batch.drop_constraint("fk_outbox_deliveries_user_event", type_="foreignkey")
        batch.drop_constraint("fk_outbox_deliveries_user", type_="foreignkey")
        batch.drop_index("ix_outbox_deliveries_user_event")
        batch.drop_index("ix_outbox_deliveries_user_id")
        batch.drop_column("user_id")
    with op.batch_alter_table("outbox_events") as batch:
        batch.drop_constraint("uq_outbox_events_user_id_id", type_="unique")
