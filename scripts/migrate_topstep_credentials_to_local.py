"""Delete hosted Topstep custody before personal-device qualification.

The command is dry-run by default. It never decrypts or prints credentials.
"""
from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from app.hosted_credential_migration import migrate_hosted_topstep_credentials


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor-user-id", type=int, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--target-user-id", type=int)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform irreversible hosted credential deletion; otherwise report scope only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        result = migrate_hosted_topstep_credentials(
            db,
            actor_user_id=args.actor_user_id,
            case_id=args.case_id,
            target_user_id=args.target_user_id,
            execute=args.execute,
        )
        print(json.dumps(result.to_dict(), sort_keys=True))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
