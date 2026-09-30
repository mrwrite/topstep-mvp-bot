# TPM key-management operations

Status: architecture and software-test procedure implemented; every step marked **PHYSICAL EVIDENCE REQUIRED** remains incomplete until executed on the production-model Raspberry Pi and discrete TPM.

## Trust boundary and inventory

The database stores AES-GCM envelopes, TPM-wrapped per-record data keys, and optional offline-recovery-wrapped copies. The Pi stores public keys and TPM handle metadata. The TPM stores the non-exportable private wrapping key. The encrypted recovery private package, its passphrase, and database backups occupy separate custody locations.

```text
credential -> random DEK -> AES-256-GCM envelope -> database/backup
                         -> TPM public wrap ------> TPM private unwrap only
                         -> recovery public wrap -> offline private ceremony only
```

Key inventory fields are: environment, purpose, version, persistent handle, TPM object name, public fingerprint, attributes, provisioned-at, active/prior/retired state, recovery key ID/fingerprint, evidence hash, approver, and retirement dependencies. No private key or authorization value belongs in the inventory.

## Target and tooling

Use the Raspberry Pi OS packages for TPM2-TSS and `tpm2-tools`; record exact signed package versions. Prefer `/dev/tpmrm0` (kernel resource manager). The application container receives that device and the host `tss` group only, drops every capability, enables `no-new-privileges`, uses a read-only root filesystem plus small tmpfs, and mounts only public metadata read-only. Privileged mode and broad host mounts are prohibited.

The provider uses a persistent RSA-2048 decrypt key, SHA-256 name algorithm, OAEP/SHA-256, and attributes `fixedtpm|fixedparent|sensitivedataorigin|decrypt|userwithauth`. Provisioning must verify the module supports that profile before enrollment. Owner, endorsement, and lockout hierarchy authentication stays offline. The application authorization is injected as a root-owned mode-0600 runtime credential and never placed in environment variables, images, backups, logs, or the repository.

PCR binding is not used. Normal firmware, bootloader, kernel, initramfs, and container updates therefore do not change an unseal policy. Adding PCR binding requires a separate authorized-policy design, update matrix, rollback drill, and lockout recovery proof.

## Provisioning ceremony — PHYSICAL EVIDENCE REQUIRED

1. Record Pi serial/model, TPM vendor/model/firmware, OS/kernel, secure-boot/measured-boot status, device nodes, tool/library versions, hierarchy state, and dictionary-attack parameters.
2. Set and escrow owner/endorsement/lockout hierarchy authentication offline. Choose an unused application handle (example only: `0x81010020`) and record the exact target.
3. Generate the RSA key inside the TPM with fixed-TPM/fixed-parent/sensitive-data-origin/decrypt/user-auth attributes. Do not import an exportable application private key.
4. Persist it under the approved owner-hierarchy handle; export only public/name data. Hash DER SubjectPublicKeyInfo with SHA-256 and place that fingerprint in approved configuration.
5. Run OAEP-SHA256 wrap/unwrap of a random 32-byte probe, inspect attributes/name, restart the container, reboot the Pi, repeat the self-test, and attach command/status/duration/output hashes with secrets redacted.
6. Prove attempts to duplicate/export the object are rejected. This is evidence about this TPM object, not a universal physical-tamper claim.

Never evict an existing handle during provisioning. A collision stops the ceremony for inventory and approval.

## Production startup and health

Production configuration explicitly selects `tpm2` and supplies key ID, active version, version-to-handle map, version-to-public-file map, approved fingerprints, `/dev/tpmrm0`, runtime auth file, recovery public-key ID/file/fingerprint, and `LEGACY_FERNET_MODE`. Startup fails for absent/unsafe devices, software-TPM markers, missing handles, fingerprint mismatch, unsafe auth-file permissions, recovery private material, unsupported algorithms/schema, failed self-test, a development provider, or an invalid legacy mode.

Health exposes provider type, availability, active/prior versions, key ID, safe classification, last self-test, rotation/migration state, and recovery-public readiness. It never exposes handles beyond approved operational status, public bytes, ciphertext contents, authentication values, recovery secrets, plaintext, or DEKs.

## Rotation state machine

`planned -> active-write -> rewrapping -> verifying -> ready-to-retire -> completed`, with explicit `paused` and `failed` states. New writes use only the active version. Workers claim rows transactionally, rewrap only the DEK, preserve ciphertext/nonce/tag, verify each record with the new TPM key, and update idempotent progress. Resume begins from authoritative committed state.

Do not evict an old handle until every protected record is inventoried, rewrapped, verified, and reconciled; restored-backup and replacement recovery evidence passes; rollback policy and exact handle are approved; and every active database/backup dependency is documented as removed or retained. Eviction requires a second operator confirmation and records rollback loss.

## Fernet migration and cutover

States are `inventory -> dry-run -> backed-up -> migrating -> verifying -> envelope-only -> rollback-retention -> destruction-approved`. Inventory counts every non-`envelope:v2:` credential. Dry-run validates record context and decryptability without mutation. Verify a restorable backup, then migrate batches with PostgreSQL row locks and idempotent commits. Reconcile inventory to zero and decrypt every new envelope before setting `LEGACY_FERNET_MODE=envelope-only`.

After cutover, remove `CREDENTIALS_ENCRYPTION_KEY` from runtime configuration and prove Fernet ciphertext is rejected. Keep encrypted legacy rollback material offline for 30 days by default, separately from backups. Destruction needs exact identity, zero dependencies, successful restore/recovery evidence, explicit owner approval, and recorded rollback implications.

## Offline recovery material

Create an RSA-3072 recovery key on an offline workstation. Encrypt its private package with an owner-approved offline mechanism. Store the package, passphrase, and database backup separately. Production receives only the public key, ID, and fingerprint. Record a signed/hash manifest covering format, algorithms, identity, creation time, custodian, and package digest.

The selected model is single-owner custody. Residual risk: compromise/coercion of that owner plus access to the encrypted package and a database backup can expose credentials; loss of the package or passphrase can make a lost-Pi backup unrecoverable. The owner must explicitly accept this or require a later multi-party design.

## Replacement-Pi recovery — PHYSICAL EVIDENCE REQUIRED

1. Declare maintenance and block credential writes/execution. Verify database backup and recovery-package manifests.
2. Provision and independently fingerprint the replacement Pi TPM key using the provisioning ceremony.
3. On the offline recovery host, unwrap one recovery DEK in memory, wrap it to the replacement TPM public key, update envelope wrapping metadata/integrity, and erase transient buffers/workspace.
4. On the replacement Pi, unwrap and verify the record/context; commit one row and append an audit event. Repeat in bounded idempotent batches.
5. Reconcile total/in-progress/succeeded/failed counts; verify wrong recovery key and corrupted artifacts fail; restart container, reboot Pi, and verify again.
6. Record commands, statuses, duration, record counts, warnings, tool/hardware versions, and evidence hashes. Do not record plaintext or key material.

## Incident procedures

- Lost/stolen Pi: suspend credential-dependent work, preserve audit/inventory, rotate external credentials where exposure is plausible, provision a replacement, restore verified backup, use offline recovery, and retire the lost key only after dependency proof.
- TPM failure: fail closed, do not substitute a software key, preserve the database, and use replacement recovery.
- TPM lockout: stop retries, record the safe error, use the offline lockout-authority procedure, inspect dictionary-attack settings, and resume only after approval/self-test.
- Recovery-key compromise: suspend recovery wrapping and credential writes, rotate external credentials as needed, create a new offline key, rewrap recovery copies, reconcile, and destroy the compromised package only after approval.
- Backup/restore: a database backup alone is intentionally insufficient. Restore remains unavailable for credential use until tombstones, envelope integrity, TPM identity, and recovery rewrap are reconciled.

## Key-retirement approval checklist

| Condition | Required proof | If absent |
|---|---|---|
| Exact target | handle, name, fingerprint, version | reject |
| Active dependencies | authoritative zero-record inventory | reject |
| Backup dependencies | retention inventory and restore result | reject |
| Recovery | replacement-TPM drill and reconciliation | reject |
| Rollback | approved window and impact | reject |
| Approval | named owner and second confirmation | reject |

Full-disk encryption is defense in depth only; it does not replace the application envelope or TPM key. A compromised running host can request authorized unwraps, Python cannot guarantee complete memory zeroization, and TPM non-exportability does not by itself prove trustworthy boot or physical tamper resistance.
