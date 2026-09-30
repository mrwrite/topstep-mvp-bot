"""Fail-closed operator ceremony for a restored hosted Topstep database.

The operator must disable provider execution and worker processing, increment
HOSTED_SECURITY_EPOCH outside the database, restore the backup, and then run
this command. It never contacts Topstep and never prints secret material.
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from app import database, models
from app.authorization import OperatorContext
from app.time_utils import utc_now
from app.topstep_session_security import reconcile_restored_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-id", required=True, type=int)
    parser.add_argument("--target-tenant-id", required=True, type=int)
    parser.add_argument("--case", required=True)
    parser.add_argument("--correlation-id", required=True)
    args = parser.parse_args()
    now = utc_now()
    db = database.SessionLocal()
    try:
        operator = db.get(models.User, args.operator_id)
        if operator is None or not operator.is_admin:
            raise SystemExit("Authorized operator identity is required.")
        result = reconcile_restored_database(db, OperatorContext(
            actor_user_id=operator.id,
            target_tenant_id=args.target_tenant_id,
            purpose="Reconcile restored hosted Topstep database",
            case_id=args.case,
            action="restore_reconciliation",
            correlation_id=args.correlation_id,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            permissions=("restore:reconcile",),
        ))
        print({
            "state": result.state,
            "source_epoch": result.source_epoch,
            "target_epoch": result.target_epoch,
            "integrations_suppressed": result.integrations_suppressed,
            "commands_suppressed": result.commands_suppressed,
            "outbox_suppressed": result.outbox_suppressed,
            "correlation_id": result.correlation_id,
        })
    finally:
        db.close()


if __name__ == "__main__":
    main()
