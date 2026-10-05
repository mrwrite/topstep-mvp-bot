from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .journal import LOCAL_SCHEMA_REVISION, LocalJournal, create_local_engine, verify_local_database
from .journal_models import Installation, LifecycleTransition, OrderIntent, ReconciliationLock
from .release import ReleaseVerification


NONTERMINAL_INTENT_STATES = frozenset({"committed", "ambiguous", "accepted"})
MUTATION_LIFECYCLE_STATES = frozenset({"practice_armed", "combine_armed", "running"})


class MaintenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaintenanceDecision:
    allowed: bool
    classification: str
    requires_preflight: bool = True
    preserve_journal: bool = True


@dataclass(frozen=True)
class BackupRecord:
    path: Path
    sha256: str
    schema_revision: str


@dataclass(frozen=True)
class IncidentPlan:
    classification: str
    steps: tuple[str, ...]
    provider_orders_cancelled: bool = False


def _halt(session: Session, installation: Installation, reason: str) -> None:
    previous = installation.lifecycle_state
    if previous != "halted":
        installation.lifecycle_state = "halted"
        session.add(
            LifecycleTransition(
                installation_id=installation.id,
                from_state=previous,
                to_state="halted",
                reason=reason,
            )
        )
    session.flush()


class UpdateCoordinator:
    """Fail-closed update and rollback admission checks.

    The coordinator never applies an executable. It creates a durable halt first,
    then decides whether an external installer may replace the verified artifact.
    """

    def prepare(
        self,
        session: Session,
        installation: Installation,
        verification: ReleaseVerification,
        *,
        target_schema_min: str = LOCAL_SCHEMA_REVISION,
        target_schema_max: str = LOCAL_SCHEMA_REVISION,
    ) -> MaintenanceDecision:
        _halt(session, installation, "software_update_requested")
        if not verification.accepted:
            return MaintenanceDecision(False, verification.classification)
        if LOCAL_SCHEMA_REVISION not in {target_schema_min, target_schema_max}:
            return MaintenanceDecision(False, "update_schema_incompatible")
        active_lock = session.scalar(
            select(ReconciliationLock.id).where(ReconciliationLock.active.is_(True)).limit(1)
        )
        nonterminal = session.scalar(
            select(OrderIntent.id).where(OrderIntent.state.in_(NONTERMINAL_INTENT_STATES)).limit(1)
        )
        if active_lock is not None or nonterminal is not None:
            return MaintenanceDecision(False, "update_ambiguous_work_preserved")
        return MaintenanceDecision(True, "update_ready")

    @staticmethod
    def complete(
        installation: Installation,
        *,
        preflight_passed: bool,
    ) -> MaintenanceDecision:
        # Updates and rollbacks cannot restore an armed/running state. A successful
        # preflight permits observe-only; every failure remains halted.
        installation.lifecycle_state = "observe_only" if preflight_passed else "halted"
        return MaintenanceDecision(
            preflight_passed,
            "update_completed_observe_only" if preflight_passed else "update_preflight_failed",
        )


class RecoveryManager:
    def backup(self, journal: LocalJournal, destination: Path) -> BackupRecord:
        backup_path = journal.backup(destination)
        digest = sha256(backup_path.read_bytes()).hexdigest()
        return BackupRecord(backup_path, digest, LOCAL_SCHEMA_REVISION)

    def validate_backup(self, record: BackupRecord) -> None:
        if not record.path.is_file() or sha256(record.path.read_bytes()).hexdigest() != record.sha256:
            raise MaintenanceError("backup_integrity_failed")
        engine = create_local_engine(record.path)
        try:
            status = verify_local_database(engine)
        finally:
            engine.dispose()
        if status["revision"] != record.schema_revision:
            raise MaintenanceError("backup_schema_mismatch")

    def restore_to_new_path(self, record: BackupRecord, destination: Path) -> Path:
        self.validate_backup(record)
        if destination.exists():
            raise MaintenanceError("restore_destination_must_not_exist")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.{uuid4().hex}.restore")
        try:
            shutil.copyfile(record.path, staging)
            if sha256(staging.read_bytes()).hexdigest() != record.sha256:
                raise MaintenanceError("restore_copy_integrity_failed")
            engine = create_local_engine(staging)
            try:
                verify_local_database(engine)
            finally:
                engine.dispose()
            os.replace(staging, destination)
        finally:
            if staging.exists():
                staging.unlink()
        return destination

    @staticmethod
    def assert_destructive_reset_allowed(session: Session, typed_confirmation: str) -> None:
        if typed_confirmation != "RESET LOCAL EXECUTOR":
            raise MaintenanceError("reset_confirmation_required")
        if session.scalar(select(ReconciliationLock.id).where(ReconciliationLock.active.is_(True)).limit(1)):
            raise MaintenanceError("reset_reconciliation_lock_active")
        if session.scalar(select(OrderIntent.id).where(OrderIntent.state.in_(NONTERMINAL_INTENT_STATES)).limit(1)):
            raise MaintenanceError("reset_nonterminal_work_active")

    @staticmethod
    def remove_credentials(
        typed_confirmation: str,
        remover: Callable[[], None],
    ) -> IncidentPlan:
        if typed_confirmation != "DELETE LOCAL CREDENTIALS":
            raise MaintenanceError("credential_deletion_confirmation_required")
        remover()
        return IncidentPlan(
            "credentials_removed_key_revocation_required",
            (
                "Verify all provider state directly in TopstepX.",
                "Revoke the dedicated API key in TopstepX.",
                "Retain the journal until every ambiguous intent is resolved.",
            ),
        )

    @staticmethod
    def uninstall_plan() -> IncidentPlan:
        return IncidentPlan(
            "uninstall_requires_provider_verification",
            (
                "Halt the local executor and do not start new entries.",
                "Verify orders and positions directly in TopstepX.",
                "Create and validate a journal backup.",
                "Remove local credentials and revoke the dedicated API key.",
                "Uninstall the executable only after preserving the journal.",
            ),
        )

    @staticmethod
    def lost_device_plan() -> IncidentPlan:
        return IncidentPlan(
            "lost_device_emergency_key_revocation",
            (
                "Revoke the dedicated Topstep API key from a trusted device.",
                "Verify and manage orders and positions directly in TopstepX.",
                "Revoke the hosted telemetry device credential.",
                "Treat the local journal as unavailable and all unknown work as ambiguous.",
                "Install a newly signed executor and repeat Practice qualification.",
            ),
        )
