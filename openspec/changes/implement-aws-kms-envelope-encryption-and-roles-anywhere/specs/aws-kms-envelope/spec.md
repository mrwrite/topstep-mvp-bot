## ADDED Requirements

> **Superseded historical requirements.** These requirements are inactive; the TPM replacement change is authoritative.

### Requirement: AWS context-bound envelope provider
The system SHALL wrap unique AES-GCM data keys with an AWS KMS customer-managed symmetric key and SHALL bind only non-secret tenant/resource context as authenticated KMS encryption context.

#### Scenario: Context mismatch
- **WHEN** ciphertext is decrypted with a different tenant, purpose, record identity, environment, or schema version
- **THEN** the operation SHALL fail closed without returning plaintext or logging secrets

### Requirement: Short-lived external workload authentication
The production deployment SHALL obtain AWS credentials through IAM Roles Anywhere or an equivalent short-lived external workload mechanism and SHALL not require permanent AWS access keys on the Pi.

#### Scenario: Missing workload identity
- **WHEN** the certificate, private key, credential helper, or trust configuration is missing or expired
- **THEN** startup or the protected operation SHALL fail closed

### Requirement: Dual-read single-write migration
The system SHALL read explicitly retained legacy ciphertext only during migration, SHALL write new credentials in the AWS envelope format, and SHALL expose rotation-needed state without exposing plaintext.

#### Scenario: Legacy re-encryption
- **WHEN** a valid legacy credential is read with an active AWS provider
- **THEN** the system SHALL produce replacement AWS ciphertext and SHALL preserve rollback evidence without retaining plaintext

### Requirement: No false production completion
The system MUST NOT mark managed-key readiness complete until real AWS, certificate, Pi/TPM, restore, disablement, rotation, and outage evidence is attached.

#### Scenario: Local test double
- **WHEN** only a local provider, mock, or LocalStack test has run
- **THEN** the managed production task SHALL remain open
