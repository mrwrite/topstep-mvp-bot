## ADDED Requirements

### Requirement: TPM-backed production wrapping
Production SHALL use an explicitly selected physical TPM 2.0 provider whose versioned RSA-OAEP-SHA256 private wrapping keys are non-exportable, identity-pinned, and required for data-key unwrapping.

#### Scenario: Production TPM unavailable
- **WHEN** the TPM device, resource manager, configured handle, approved fingerprint, authorization, or self-test is unavailable or invalid
- **THEN** startup and credential-dependent execution SHALL fail closed before accepting credential writes

#### Scenario: Development provider in production
- **WHEN** production selects an emulated, file-based, environment-key, or development provider
- **THEN** startup SHALL fail without fallback

### Requirement: Canonical context-bound envelope
Every protected record SHALL use a unique random AES-256 data key and nonce in a versioned AES-GCM envelope that authenticates tenant, purpose, record identity, environment, schema, algorithm, provider, wrapping-key identity, and key version.

#### Scenario: Context or envelope substitution
- **WHEN** an envelope is copied across tenants, purposes, records, environments, schemas, or key versions, or any authenticated field is corrupted, truncated, or ambiguous
- **THEN** decryption SHALL fail without plaintext or sensitive diagnostic output

### Requirement: Provider lifecycle and safe status
The provider boundary SHALL expose typed readiness, identity, version, generation, wrap, unwrap, context validation, rotation, recovery rewrap, health, self-test, shutdown, and cleanup operations without exposing authorization values or secret key material.

#### Scenario: Safe health report
- **WHEN** an operator requests key-management status
- **THEN** the system SHALL return provider type, availability, active and approved prior versions, rotation and migration states, recovery readiness, self-test time, and safe failure classification only

### Requirement: Resumable data-key rotation
Rotation SHALL switch new writes to the active version and idempotently rewrap existing data keys while retaining approved prior versions until authoritative dependency reconciliation permits retirement.

#### Scenario: Partial rotation restart
- **WHEN** a rotation worker crashes before or after a committed record update
- **THEN** retry SHALL resume without double migration, plaintext re-encryption, or loss of an approved readable version

#### Scenario: Premature retirement
- **WHEN** any record, backup, recovery, verification, rollback, or approval dependency remains unresolved
- **THEN** old-key eviction SHALL be rejected

### Requirement: Offline replacement-device recovery
Recovery SHALL use a separate offline private key absent from production and SHALL rewrap recovered data keys to a provisioned replacement TPM through an explicit audited ceremony.

#### Scenario: Isolated artifact theft
- **WHEN** an attacker obtains only a database backup, only Pi storage, or only the encrypted recovery package
- **THEN** that artifact alone SHALL not expose protected credentials

#### Scenario: Replacement Pi recovery
- **WHEN** approved recovery material and a verified database backup are presented during maintenance
- **THEN** records SHALL be rewrapped to the replacement TPM, individually verified, reconciled, and audited without persisting plaintext credentials or data keys unnecessarily

### Requirement: Physical evidence boundary
Mocked or software-TPM tests SHALL NOT satisfy physical non-exportability, reboot, lockout, failure, rotation, or replacement-device recovery gates.

#### Scenario: Mock-only verification
- **WHEN** deterministic provider tests pass without a physical Raspberry Pi and TPM evidence package
- **THEN** hardware-dependent tasks and invite-only beta readiness SHALL remain open
