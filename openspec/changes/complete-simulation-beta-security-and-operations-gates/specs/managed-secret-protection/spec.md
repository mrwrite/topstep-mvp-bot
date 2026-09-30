## ADDED Requirements

### Requirement: Context-bound envelope encryption
The system SHALL encrypt every stored integration secret with authenticated envelope encryption using a unique data key and SHALL bind tenant, purpose, record type, record identity, format version, and key version as authenticated context.

#### Scenario: Context mismatch
- **WHEN** ciphertext is decrypted with a different tenant or record context
- **THEN** decryption SHALL fail without returning plaintext or logging secret material

#### Scenario: Ciphertext tampering
- **WHEN** any authenticated envelope field is modified
- **THEN** decryption SHALL fail with a sanitized security event

### Requirement: Safe key rotation and outage behavior
The system SHALL decrypt active and explicitly retained previous key versions, SHALL support lazy re-encryption, and MUST fail closed for missing, retired, invalid, or unavailable keys.

#### Scenario: Previous key during rotation
- **WHEN** a valid envelope references a retained previous key
- **THEN** the system SHALL decrypt it and mark it eligible for re-encryption under the active key

#### Scenario: Key provider outage
- **WHEN** the key provider cannot wrap or unwrap a key
- **THEN** the secret operation SHALL fail without plaintext fallback

### Requirement: Production managed-key enforcement
Production startup MUST require an explicitly selected physical TPM 2.0 provider and MUST reject development, emulated, file/environment master-key, cloud, missing, identity-mismatched, unsafe-permission, recovery-private, legacy-after-cutover, and self-test-failed configurations.

#### Scenario: Development provider in production
- **WHEN** production configuration selects the local development provider
- **THEN** startup SHALL fail before accepting traffic

### Requirement: Physical TPM wrapping authority
Production SHALL wrap each unique per-record data key with a versioned non-exportable TPM RSA-OAEP-SHA256 key and SHALL require that TPM for normal unwrapping.

#### Scenario: Mock-only evidence
- **WHEN** deterministic TPM doubles pass without physical Raspberry Pi provisioning, reboot, non-exportability, failure, rotation, and replacement-device evidence
- **THEN** the hardware secret gate SHALL remain open

### Requirement: Offline recovery separation
Production SHALL store only an approved recovery public key while the encrypted recovery private material remains offline and separate from database backups.

#### Scenario: Replacement-device restore
- **WHEN** a verified backup is restored after loss of the Pi
- **THEN** credential use SHALL remain blocked until an explicit audited ceremony rewraps and verifies every protected data key to the replacement TPM

### Requirement: Data-key-only rotation
Rotation SHALL use new writes only under the active version and SHALL rewrap existing data keys idempotently without re-encrypting credential plaintext or reusing AES-GCM nonces.

#### Scenario: Prior key retirement requested
- **WHEN** any active record, backup, recovery, verification, rollback, inventory, or approval dependency remains
- **THEN** retirement or eviction SHALL be rejected

### Requirement: Explicit legacy cutover
Fernet reads SHALL be available only during an explicit migration window and SHALL be rejected in envelope-only mode after authoritative inventory reaches zero.

#### Scenario: Fernet value after cutover
- **WHEN** legacy ciphertext is presented after envelope-only cutover
- **THEN** decryption SHALL fail without file, environment, Fernet, or development-provider fallback

### Requirement: Explicit hosted Combine provider exception
The system SHALL permit `railway-secret-envelope-v1` only for the `hosted_topstep_combine_beta` deployment profile, with independently generated versioned 256-bit keys and documented Railway administrator/runtime exposure; arbitrary environment/file master keys remain prohibited.

#### Scenario: Hosted provider used in another profile
- **WHEN** the Railway provider is selected outside the explicit hosted Combine profile
- **THEN** startup SHALL fail before credential writes or worker execution are accepted

### Requirement: Hosted Topstep credential generations are separately protected
The hosted Combine profile SHALL envelope the username, API key, and any durably required session token as separate tenant/integration/generation-bound records and SHALL use a dedicated keyed fingerprint secret for duplicate detection.

#### Scenario: Credential generation is replaced
- **WHEN** a validated replacement becomes current
- **THEN** the prior encrypted session and all prior-generation authorization SHALL be revoked without returning either credential generation to the browser
### Requirement: Hosted provider sessions are database-authoritative
For the scoped hosted Combine profile, encrypted provider sessions SHALL bind tenant, integration, credential generation, session generation, and security epoch, and renewal SHALL use a durable lease and fence rather than process-local authority.

#### Scenario: Stale renewal attempts to commit
- **WHEN** replacement, revocation, deletion, takeover, or epoch reconciliation changed authority
- **THEN** the stale token write fails closed and cannot make the integration executable
