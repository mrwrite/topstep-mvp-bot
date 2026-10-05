from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import sqlite3
import stat
import subprocess

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


LOCAL_SCHEMA_REVISION = "0001_local_journal"


class LocalJournalError(RuntimeError):
    pass


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def apply_user_only_permissions(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        domain = os.environ.get("USERDOMAIN", "").strip()
        username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
        principal = f"{domain}\\{username}" if domain else username
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:(OI)(CI)F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise LocalJournalError("user_only_permissions_failed")
    else:
        path.chmod(stat.S_IRWXU)


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


def create_local_engine(path: Path) -> Engine:
    engine = create_engine(sqlite_url(path), future=True)
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def alembic_config(path: Path) -> Config:
    root = Path(__file__).resolve().parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(path))
    return config


def upgrade_local_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(path), "head")


def integrity_status(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_violations = connection.execute(text("PRAGMA foreign_key_check")).all()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
    return {
        "integrity": integrity,
        "foreign_key_violations": len(foreign_key_violations),
        "revision": revision,
        "journal_mode": str(journal_mode).lower(),
        "foreign_keys": int(foreign_keys),
        "busy_timeout": int(busy_timeout),
    }


def verify_local_database(engine: Engine) -> dict[str, object]:
    try:
        status = integrity_status(engine)
    except Exception as exc:
        raise LocalJournalError("journal_integrity_check_failed") from exc
    if status["integrity"] != "ok" or status["foreign_key_violations"] != 0:
        raise LocalJournalError("journal_integrity_failed")
    if status["revision"] != LOCAL_SCHEMA_REVISION:
        raise LocalJournalError("journal_schema_revision_unsupported")
    if status["journal_mode"] != "wal" or status["foreign_keys"] != 1:
        raise LocalJournalError("journal_safety_pragmas_unavailable")
    if int(status["busy_timeout"]) < 5000:
        raise LocalJournalError("journal_busy_timeout_too_low")
    return status


@dataclass
class LocalJournal:
    path: Path
    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def open(cls, path: Path, *, migrate: bool = True, secure_permissions: bool = True) -> "LocalJournal":
        if secure_permissions:
            apply_user_only_permissions(path.parent)
        if migrate:
            upgrade_local_database(path)
        engine = create_local_engine(path)
        verify_local_database(engine)
        return cls(path, engine, sessionmaker(bind=engine, expire_on_commit=False))

    def close(self) -> None:
        self.engine.dispose()

    def backup(self, destination: Path) -> Path:
        verify_local_database(self.engine)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        if os.name != "nt":
            destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return destination
