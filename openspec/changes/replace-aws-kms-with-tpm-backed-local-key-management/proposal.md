## Why

The owner has prohibited AWS and every hosted key-management service. Production on a self-hosted Raspberry Pi therefore needs application-level envelope encryption whose wrapping private key is non-exportable in a physical TPM 2.0, plus an offline recovery path that does not copy that TPM key.

## What Changes

- **BREAKING**: remove AWS SDKs, AWS configuration, IAM Roles Anywhere, cloud templates, and active operational guidance.
- Replace the AWS provider with an explicit TPM 2.0 provider using RSA-OAEP with SHA-256 through TPM2-TSS tooling.
- Version the canonical AES-256-GCM envelope and authenticate tenant, purpose, record, environment, schema, and wrapping-key version.
- Add offline recovery wrapping, resumable data-key-only rotation, and controlled Fernet migration/cutover behavior.
- Fail production startup unless a physical TPM, approved key identity, safe device permissions, recovery public configuration, and provider self-test succeed.
- Keep physical-Pi provisioning, non-exportability, reboot, recovery, production migration, and destructive retirement tasks open until real evidence exists.

## Capabilities

### New Capabilities

- `tpm-key-management`: TPM-backed wrapping, production enforcement, versioned envelope encryption, rotation, health, and offline replacement-device recovery.
- `credential-key-migration`: authoritative Fernet inventory, resumable conversion, envelope-only cutover, rollback retention, and retirement controls.

### Modified Capabilities

- `managed-secret-protection`: replace the managed-cloud-KMS requirement with mandatory hardware-backed local key management and physical evidence.
- `account-deletion-backup-handling`: require recovery rewrapping and key-dependency evidence for backup restore and destructive key actions.
- `release-governance`: make physical TPM, replacement-Pi recovery, migration, warning, install, backup, approval, and protected-CI evidence independent release vetoes.
- `beta-operations`: add TPM provisioning, failure, lockout, rotation, recovery, lost-device, and key-retirement operating gates.

## Impact

Affected areas include `app/key_management.py`, credential crypto/configuration, database migration state, Raspberry Pi/container deployment documentation, CI architectural checks, dependency locks, key-management tests, and the parent and superseded child OpenSpec evidence. Broker execution and live-money behavior are unchanged and remain disabled.

## Hosted-beta deferral decision (2026-09-24)

The owner changed the immediate target to a one-user Railway-hosted Topstep Trading Combine beta. This change remains authoritative for the planned self-hosted Raspberry Pi profile and future live/live-credential readiness, but its physical provisioning, non-exportability, replacement-Pi recovery, production Fernet migration, retirement, and operational-approval tasks are deferred and non-blocking only for that hosted stage. No task is completed by this deferral and no physical TPM claim is made. The hosted implementation is tracked by `deploy-invite-only-topstep-combine-beta-to-vercel-and-railway`.
