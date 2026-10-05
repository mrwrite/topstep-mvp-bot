from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.hosted_credential_migration import migrate_hosted_topstep_credentials


def test_operator_migration_is_dry_run_by_default_and_deletes_without_decrypting(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        operator = models.User(
            username="operator", email="operator@example.test", hashed_password="x", is_admin=1
        )
        tester = models.User(
            username="tester", email="tester@example.test", hashed_password="x"
        )
        db.add_all([operator, tester])
        db.flush()
        integration = models.PlatformIntegration(
            user_id=tester.id,
            display_name="hosted-topstep",
            provider="topstepx",
            status="validated",
            security_epoch=1,
            integration_metadata={"credential_generation": 1},
        )
        db.add(integration)
        db.flush()
        credential = models.TopstepCredential(
            user_id=tester.id,
            integration_id=integration.id,
            lifecycle_status="validated",
            username_encrypted="opaque-username",
            api_key_encrypted="opaque-api-key",
            credential_schema_version=1,
            credential_fingerprint="fixture-fingerprint",
            encryption_key_version="v1",
            credential_generation=1,
            security_epoch=1,
            is_current=1,
        )
        db.add(credential)
        db.commit()

        preview = migrate_hosted_topstep_credentials(
            db,
            actor_user_id=operator.id,
            case_id="LOCAL-CUSTODY-001",
            target_user_id=tester.id,
        )
        assert preview.to_dict() == {
            "matched_integrations": 1,
            "deleted_integrations": 0,
            "api_key_rotation_required": True,
            "dry_run": True,
        }
        db.refresh(credential)
        assert credential.api_key_encrypted == "opaque-api-key"

        result = migrate_hosted_topstep_credentials(
            db,
            actor_user_id=operator.id,
            case_id="LOCAL-CUSTODY-001",
            target_user_id=tester.id,
            execute=True,
        )
        assert result.deleted_integrations == 1
        db.refresh(integration)
        db.refresh(credential)
        assert integration.status == "deleted"
        assert integration.integration_metadata["custody_migrated_to"] == "personal_device_executor"
        assert integration.integration_metadata["api_key_rotation_required"] is True
        assert credential.username_encrypted is None
        assert credential.api_key_encrypted is None
        assert credential.lifecycle_status == "deleted"
        assert db.query(models.TopstepIntegrationTombstone).filter_by(
            integration_id=integration.id
        ).one()
        audit = db.query(models.SecurityAuditEvent).filter_by(
            event_type="topstep_credential_custody_migration"
        ).one()
        assert audit.event_metadata["api_key_rotation_required"] is True
        assert "opaque" not in str(result.to_dict())
    finally:
        db.close()
        engine.dispose()
