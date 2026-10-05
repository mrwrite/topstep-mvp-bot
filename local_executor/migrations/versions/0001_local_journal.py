"""Create the independent local execution journal."""
from __future__ import annotations

from alembic import op

from local_executor.journal_models import LocalBase


revision = "0001_local_journal"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    LocalBase.metadata.create_all(bind=op.get_bind())
    op.execute(
        "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
        "BEGIN SELECT RAISE(ABORT, 'audit_events_append_only'); END"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
        "BEGIN SELECT RAISE(ABORT, 'audit_events_append_only'); END"
    )
    op.execute(
        "CREATE TRIGGER order_intents_immutable BEFORE UPDATE ON order_intents "
        "WHEN OLD.installation_id != NEW.installation_id "
        "OR OLD.account_binding_id != NEW.account_binding_id "
        "OR OLD.strategy_decision_id != NEW.strategy_decision_id "
        "OR OLD.policy_version_id != NEW.policy_version_id "
        "OR COALESCE(OLD.risk_decision_id, '') != COALESCE(NEW.risk_decision_id, '') "
        "OR OLD.action != NEW.action OR OLD.custom_tag != NEW.custom_tag "
        "OR OLD.contract_id != NEW.contract_id OR OLD.side != NEW.side "
        "OR OLD.order_type != NEW.order_type OR OLD.quantity != NEW.quantity "
        "OR COALESCE(OLD.target_provider_id, '') != COALESCE(NEW.target_provider_id, '') "
        "OR COALESCE(OLD.limit_price, '') != COALESCE(NEW.limit_price, '') "
        "OR COALESCE(OLD.stop_price, '') != COALESCE(NEW.stop_price, '') "
        "OR COALESCE(OLD.trail_price, '') != COALESCE(NEW.trail_price, '') "
        "OR OLD.request_hash != NEW.request_hash OR OLD.origin != NEW.origin "
        "BEGIN SELECT RAISE(ABORT, 'order_intent_immutable'); END"
    )


def downgrade() -> None:
    LocalBase.metadata.drop_all(bind=op.get_bind())
