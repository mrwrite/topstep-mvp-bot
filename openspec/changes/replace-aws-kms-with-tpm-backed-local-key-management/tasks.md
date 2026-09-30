## 1. AWS Removal and Supersession

- [x] 1.1 Inventory and classify every AWS artifact, retain provider-neutral work, and mark the AWS child superseded without completing its open tasks.
- [x] 1.2 Remove AWS SDK/lock entries, runtime imports/configuration, tests, infrastructure templates, IAM Roles Anywhere material, and active documentation.
- [x] 1.3 Add CI architectural enforcement prohibiting active AWS/cloud-KMS artifacts and key-management boundary violations.

## 2. Provider-Neutral Cryptography

- [x] 2.1 Refactor typed provider lifecycle operations, readiness/health, context validation, cleanup, and production-safe development provider behavior.
- [x] 2.2 Implement canonical schema-2 AES-256-GCM envelopes with strict authenticated context, per-record data keys/nonces, recovery wrap, and fail-closed parsing.
- [x] 2.3 Add deterministic provider-neutral context, tamper, uniqueness, truncation, unsupported-policy, restart, and redaction tests.

## 3. TPM Provider

- [x] 3.1 Implement the TPM2-TSS/tpm2-tools provider boundary with persistent-handle identity/fingerprint checks, OAEP-SHA256 unwrap, bounded subprocess behavior, readiness, and safe failures.
- [x] 3.2 Enforce explicit physical-TPM production configuration, unsafe permission/recovery-private-material rejection, self-test, and safe health reporting.
- [x] 3.3 Add deterministic TPM command-adapter tests for missing device/key, wrong identity, command failure, lockout/auth failure, and software-provider rejection.
- [ ] 3.4 DEFERRED FOR HOSTED COMBINE ONLY: provision the production Raspberry Pi physical TPM key and record exact model, firmware, tool versions, attributes, handle, name, and fingerprint evidence.
- [ ] 3.5 DEFERRED FOR HOSTED COMBINE ONLY: prove physical TPM non-exportability and restart/reboot/upgrade behavior on the target Raspberry Pi.

## 4. Rotation, Recovery, and Migration

- [x] 4.1 Implement data-key-only rewrap primitives and durable versioned rotation/migration state with idempotent progress, pause/resume, verification, reconciliation, and retirement guards.
- [x] 4.2 Implement offline recovery public-key wrapping and an audited replacement-TPM rewrap workflow with artifact integrity verification.
- [x] 4.3 Implement explicit Fernet inventory/dry-run/migration/envelope-only cutover and runtime legacy rejection policy.
- [x] 4.4 Add deterministic rotation, recovery, wrong-key/corruption, legacy retry/cutover, concurrency, duplicate-worker, and crash-boundary tests.
- [ ] 4.5 Run PostgreSQL concurrent migration/rotation and backup-restore verification and retain command/test evidence.
- [ ] 4.6 DEFERRED FOR HOSTED COMBINE ONLY: run a physical replacement-Pi recovery drill against a restored database backup and reconcile every protected record.
- [ ] 4.7 DEFERRED FOR HOSTED COMBINE ONLY: complete self-hosted production Fernet migration to zero active records, enable envelope-only mode, remove the runtime legacy key, and retain encrypted rollback material offline.
- [ ] 4.8 DEFERRED FOR HOSTED COMBINE ONLY: obtain explicit owner approval before retiring old TPM keys or destroying legacy/recovery material.

## 5. Raspberry Pi Operations

- [x] 5.1 Add least-privilege container device/group/read-only-filesystem integration and Raspberry Pi provisioning, rotation, recovery, backup, lost/stolen, TPM failure/lockout, compromise, and retirement runbooks.
- [ ] 5.2 DEFERRED FOR HOSTED COMBINE ONLY: record real Pi container restart, host reboot, TPM outage/lockout, rotation, safe logging, upgrade, and failure-recovery evidence.
- [ ] 5.3 DEFERRED FOR HOSTED COMBINE ONLY: obtain operational approval for custodians, authorization delivery, handle allocation, recovery risk, rollback window, and destructive procedures.

## 6. OpenSpec and Verification

- [x] 6.1 Reconcile parent design, tasks, readiness, traceability, credential, account lifecycle, release, and operations artifacts with the owner decision and hardware evidence matrix.
- [x] 6.2 Add the AWS inventory, TPM trust boundary, envelope contract, recovery threat model, rotation state machine, retirement table, startup rules, and residual-risk documentation.
- [x] 6.3 Run available backend, frontend, dependency, migration, architectural, smoke, and strict OpenSpec checks; record exact results and limitations.
- [ ] 6.4 Obtain protected-host CI evidence and close only after warning, installation, backup, cohort, operator-outcome, migration, hardware, recovery, and operational gates pass.
