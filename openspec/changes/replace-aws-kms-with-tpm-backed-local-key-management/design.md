## Context

The AWS child produced useful provider-neutral envelope code but selected a prohibited cloud dependency. The production target is a Raspberry Pi with a discrete physical TPM 2.0 exposed to a rootless application container. The database and Pi storage are assumed stealable; the TPM resists private-key extraction but does not protect plaintext after an authorized application unwrap. Recovery must survive total Pi loss without exporting the TPM key.

## Goals / Non-Goals

**Goals:**

- Keep every record under a unique random AES-256 data key and 96-bit nonce.
- Require a non-exportable, versioned TPM RSA private key for production unwrap.
- Authenticate canonical tenant, purpose, record, environment, schema, algorithm, and key-version metadata.
- Rewrap data keys without re-encrypting credential plaintext.
- Permit an explicit, audited replacement-Pi ceremony using a separate offline private key.
- Make production startup and credential-dependent work fail closed.

**Non-Goals:**

- Cloud KMS, hosted vaults, broker/live-money activation, remote attestation claims, or compliance claims.
- Treating disk encryption as application key protection.
- Claiming physical non-exportability, reboot behavior, or recovery from mocked tests.
- Automatic destructive eviction of prior TPM keys or legacy-key deletion.

## Decisions

### TPM interface and key shape

The production adapter invokes pinned `tpm2-tools` commands only inside `Tpm2KeyProvider`; application code never shells out. TPM2-TSS is the maintained underlying stack, and Linux `/dev/tpmrm0` is preferred so the kernel resource manager mediates concurrent TPM access. The container receives only that device, the `tss` group, a read-only root filesystem, and a small tmpfs for mode-0600 transient input/output. It does not require `--privileged`, host-root mounts, or added capabilities.

Each key version maps to an owner-hierarchy persistent handle and an approved SHA-256 fingerprint of its exported public key. Provisioning creates RSA-2048 `fixedtpm|fixedparent|sensitivedataorigin|decrypt|userwithauth` material, verifies OAEP/SHA-256 capability, persists it with `tpm2_evictcontrol`, exports only the public key, and records handle, name, fingerprint, version, and evidence. Production unwrap uses `tpm2_rsadecrypt -s oaep` with the persistent handle. Wrap uses the verified public key through `cryptography` with OAEP SHA-256/MGF1-SHA256, which avoids sending a public operation through the TPM.

The key is not PCR-bound initially. Raspberry Pi firmware, kernel, initramfs, bootloader, and container updates make a naive PCR policy operationally fragile. TPM possession, object attributes, device permissions, key authorization delivery, fingerprint pinning, and fail-closed self-test are the initial controls. Measured-boot policy can be a later owner-approved change with signed-policy recovery evidence.

PKCS#11 was rejected for the first implementation because it adds token-store/PIN lifecycle and another translation layer without improving the envelope boundary. A Python TPM binding was rejected because none is already pinned and target-OS compatibility has not been demonstrated. Raw ESAPI may replace the command adapter later without changing application contracts.

Owner, endorsement, and lockout hierarchy authentication is provisioned offline and never delivered to the application. The application key has its own authorization source supplied through a root-owned descriptor/credential mechanism; it is never logged or returned to callers. Dictionary-attack lockout values and recovery are recorded during provisioning. Empty authorization is forbidden in production.

### Provider-neutral boundary

`KeyManagementProvider` exposes readiness, identity, key versions, generation, wrap, unwrap, context validation, rewrap, self-test/health, recovery rewrap, and shutdown. Typed error codes separate unavailable device, missing key, identity mismatch, authorization/lockout, integrity/context, unsupported policy, and unsafe configuration without embedding command output or sensitive buffers. The local development provider is visibly named and production rejects it.

### Envelope contract

Schema version 2 is canonical JSON prefixed by `envelope:v2:`. It stores algorithm identifiers, safe context fields, TPM key ID/version, wrapped key, 96-bit nonce, AES-GCM ciphertext and tag, SHA-256 of canonical context, creation time, optional migration source, and optional recovery-key ID plus recovery-wrapped data key. Base64url uses strict decoding. Authentication is deliberately split so rotation can replace only wrapped data-key metadata: AES-GCM AAD binds the immutable tenant, purpose, record ID, environment, envelope schema, context schema, and encryption algorithm, while a data-key-derived HMAC binds the wrapping algorithm, provider ID, wrapping-key ID/version, wrapped data key, recovery-key ID/wrap, context hash, creation time, and migration source. All stored metadata is reconstructed and verified before plaintext is returned; substitution, truncation, ambiguity, and unknown fields/algorithms fail closed.

The 32-byte data key exists only as a short-lived mutable buffer where practical and is overwritten in `finally` blocks. Python cannot guarantee compiler/runtime zeroization, so process memory compromise remains a residual risk.

### Offline recovery

The owner creates a distinct RSA-3072 recovery key offline. Only its public key, stable ID, and fingerprint reach production. New envelopes optionally contain a second OAEP-SHA256 wrapping of the same data key. The encrypted recovery private package, its manifest/hash, and its passphrase are stored separately from each other and from database backups. A backup alone, Pi storage alone, or recovery package alone is insufficient.

Recovery is an explicit offline tool: verify backup and manifest; provision and fingerprint the replacement Pi TPM key; enter maintenance mode; decrypt one recovery-wrapped data key in memory; wrap it to the replacement TPM public key; verify with the replacement TPM; commit the envelope update and append an audit record; reconcile all records; then destroy transient workspace. The owner accepts single-custodian recovery-key risk unless a later policy adds multi-party custody.

### Rotation and legacy migration

Rotation state is `planned -> active-write -> rewrapping -> verifying -> ready-to-retire -> completed`, with `paused` and `failed` side states. New writes switch to the active version before workers claim idempotent batches. Workers lock records, unwrap only the data key with an approved prior key, wrap it to the active public key, update the context/key version and AES-GCM tag without exposing record plaintext beyond the verification decrypt, and record progress. Retirement is rejected until inventory, verification, backup/recovery evidence, rollback policy, and dependency reconciliation are authoritative.

Fernet migration is explicit, not silent fallback: `inventory -> dry-run -> backed-up -> migrating -> verifying -> envelope-only -> rollback-retention -> destruction-approved`. Legacy reads require a migration flag and key; envelope-only mode rejects Fernet. After zero active legacy records and reconciliation, runtime loses the Fernet key immediately. Encrypted rollback material is retained offline for 30 days by default; destruction needs exact target, evidence, owner approval, and rollback acknowledgement.

## Risks / Trade-offs

- [TPM command latency or serialization] -> use `/dev/tpmrm0`, bounded timeouts, health classification, and no unbounded retries.
- [The host can use the TPM while compromised] -> least privilege, key authorization, narrow app purpose, audit, rotation, and incident response; TPM non-exportability is not host attestation.
- [Persistent handle points to a substituted key] -> compare public fingerprint and TPM object name at every readiness check.
- [Single offline recovery key compromise] -> encrypted offline storage separated from backups, integrity manifest, ceremony, audit, and owner-accepted custody risk.
- [Python buffer copies] -> minimize lifetime and scope, overwrite mutable copies, sanitize exceptions, and document residual memory risk.
- [No initial PCR binding] -> avoids update lockouts; measured boot remains a future separately tested control.
- [Physical evidence unavailable here] -> keep hardware, reboot, non-exportability, replacement recovery, migration, retirement, and production approval tasks open.

## Migration Plan

1. Remove all active AWS code, packages, templates, configuration, tests, and operator guidance; mark the old child superseded without completing its four open tasks.
2. Deploy schema-2 reader/writer and development doubles; provision recovery public material and a physical TPM key before production startup is possible.
3. Inventory Fernet rows, run dry-run and verified backup, migrate idempotently, and reconcile zero legacy dependencies.
4. Enable envelope-only mode, remove the runtime Fernet key, retain encrypted rollback material offline for 30 days, and obtain destruction approval later.
5. Drill restart, reboot, rotation, TPM failure/lockout, database restore, and replacement-Pi recovery on physical equipment.

Rollback before envelope-only cutover keeps the old application and offline legacy material. After cutover, rollback is a controlled maintenance action requiring owner approval; no automatic Fernet fallback exists.

## Open Questions

- Exact Raspberry Pi model, TPM module/vendor/firmware, OS release, and TPM2-TSS/tpm2-tools package versions require physical inventory.
- Owner must approve the persistent-handle allocation, application authorization delivery mechanism, recovery custodian, 30-day rollback window, and final retirement/destruction actions.
- PCR binding remains intentionally deferred until a measured-boot update/recovery drill can demonstrate operability.

## Hosted-beta deferral boundary

Owner decision 2026-09-24 defers this design's physical evidence for the one-user Railway Topstep Trading Combine stage only. The hosted stage uses the separately specified `railway-secret-envelope-v1` provider and explicitly accepts that Railway administrators and a compromised authorized runtime can access its service variable. That provider is not TPM-equivalent. This TPM design, all incomplete hardware/replacement-Pi/migration/approval tasks, and all historical evidence remain intact for the self-hosted profile and future live/live-credential readiness.
