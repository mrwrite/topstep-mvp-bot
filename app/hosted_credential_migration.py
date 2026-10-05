"""One-way migration from hosted Topstep custody to the local executor."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .authorization import TenantContext
from .topstep_onboarding import delete


@dataclass(frozen=True)
class HostedCredentialMigrationResult:
    matched_integrations: int
    deleted_integrations: int
    rotation_required: bool
    dry_run: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "matched_integrations": self.matched_integrations,
            "deleted_integrations": self.deleted_integrations,
            "api_key_rotation_required": self.rotation_required,
            "dry_run": self.dry_run,
        }


def migrate_hosted_topstep_credentials(
    db: Session,
    *,
    actor_user_id: int,
    case_id: str,
    target_user_id: int | None = None,
    execute: bool = False,
) -> HostedCredentialMigrationResult:
    if actor_user_id <= 0:
        raise ValueError("operator_identity_required")
    if not case_id.strip():
        raise ValueError("operator_case_required")
    query = db.query(models.PlatformIntegration).filter(
        func.lower(models.PlatformIntegration.provider) == "topstepx",
        models.PlatformIntegration.status != "deleted",
    )
    if target_user_id is not None:
        query = query.filter(models.PlatformIntegration.user_id == target_user_id)
    integrations = query.order_by(models.PlatformIntegration.user_id, models.PlatformIntegration.id).all()
    if not execute:
        return HostedCredentialMigrationResult(len(integrations), 0, bool(integrations), True)

    deleted = 0
    for integration in integrations:
        tenant = TenantContext(
            user_id=integration.user_id,
            username=f"tenant-{integration.user_id}",
            actor_user_id=actor_user_id,
            roles=("operator",),
            permissions=("topstep_credentials:migrate_local",),
            source="operator_migration",
        )
        delete(
            db,
            tenant,
            integration_id=integration.id,
            audit_action="hosted_credentials_deleted_for_local_executor",
        )
        integration = db.get(models.PlatformIntegration, integration.id)
        metadata = dict(integration.integration_metadata or {})
        metadata.update(
            {
                "deleted": True,
                "custody_migrated_to": "personal_device_executor",
                "api_key_rotation_required": True,
                "migration_case_id": case_id,
            }
        )
        integration.integration_metadata = metadata
        db.add(
            models.SecurityAuditEvent(
                actor_user_id=actor_user_id,
                target_user_id=integration.user_id,
                event_type="topstep_credential_custody_migration",
                action="require_dedicated_api_key_rotation",
                reason="Hosted Topstep custody superseded by personal-device executor.",
                case_id=case_id,
                outcome="rotation_required",
                event_metadata={
                    "integration_id": integration.id,
                    "hosted_credentials_deleted": True,
                    "provider_sessions_deleted": True,
                    "api_key_rotation_required": True,
                },
            )
        )
        db.commit()
        deleted += 1
    return HostedCredentialMigrationResult(len(integrations), deleted, bool(integrations), False)
