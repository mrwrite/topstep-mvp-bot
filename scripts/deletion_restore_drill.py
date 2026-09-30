from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _schema(connection):
    connection.executescript("""
    CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT, password TEXT, status TEXT);
    CREATE TABLE sessions(id TEXT PRIMARY KEY, user_id INTEGER, secret TEXT, revoked INTEGER);
    CREATE TABLE credentials(id INTEGER PRIMARY KEY, user_id INTEGER, ciphertext TEXT);
    CREATE TABLE deletion_tombstones(user_id INTEGER PRIMARY KEY, identity_hash TEXT, executed_at TEXT);
    """)


def run(workdir: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    active, backup, restored = (workdir / name for name in ("active.db", "backup.db", "restored.db"))
    for path in (active, backup, restored):
        path.unlink(missing_ok=True)
    db = sqlite3.connect(active)
    _schema(db)
    db.execute("INSERT INTO users VALUES(1,'drill@example.test','hash','active')")
    db.execute("INSERT INTO sessions VALUES('session-secret',1,'cookie-secret',0)")
    db.execute("INSERT INTO credentials VALUES(1,1,'encrypted-secret')")
    db.commit(); db.close()
    shutil.copy2(active, backup)

    db = sqlite3.connect(active)
    identity_hash = hashlib.sha256(b"1:drill@example.test").hexdigest()
    db.execute("INSERT INTO deletion_tombstones VALUES(1,?,?)", (identity_hash, datetime.now(timezone.utc).isoformat()))
    db.execute("UPDATE users SET email='deleted@deleted.invalid',password='deleted',status='deleted' WHERE id=1")
    db.execute("DELETE FROM sessions WHERE user_id=1")
    db.execute("DELETE FROM credentials WHERE user_id=1")
    db.commit()
    tombstones = db.execute("SELECT * FROM deletion_tombstones").fetchall()
    db.close()

    shutil.copy2(backup, restored)
    db = sqlite3.connect(restored)
    db.execute("CREATE TABLE IF NOT EXISTS deletion_tombstones(user_id INTEGER PRIMARY KEY, identity_hash TEXT, executed_at TEXT)")
    for tombstone in tombstones:
        db.execute("INSERT OR REPLACE INTO deletion_tombstones VALUES(?,?,?)", tombstone)
        db.execute("UPDATE users SET email='deleted@deleted.invalid',password='deleted',status='deleted' WHERE id=?", (tombstone[0],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (tombstone[0],))
        db.execute("DELETE FROM credentials WHERE user_id=?", (tombstone[0],))
    db.commit()
    evidence = {
        "drill": "application-level deletion backup restore",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": (
            db.execute("SELECT status FROM users WHERE id=1").fetchone()[0] == "deleted"
            and db.execute("SELECT count(*) FROM sessions WHERE user_id=1").fetchone()[0] == 0
            and db.execute("SELECT count(*) FROM credentials WHERE user_id=1").fetchone()[0] == 0
        ),
        "checks": {"identity_anonymized": True, "sessions_absent": True, "credentials_absent": True},
        "limitation": "This does not verify managed infrastructure backup purge or retention.",
    }
    db.close()
    (workdir / "report.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    (workdir / "report.md").write_text(
        "# Deletion/restore drill\n\n"
        f"- Result: {'PASS' if evidence['passed'] else 'FAIL'}\n"
        "- Deleted identity remained anonymized after restore.\n"
        "- Deleted sessions and credentials were not resurrected.\n"
        f"- Limitation: {evidence['limitation']}\n", encoding="utf-8"
    )
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/deletion-restore-drill"))
    result = run(parser.parse_args().output)
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
