## ADDED Requirements

### Requirement: Credential tombstone blocks all reuse
Disconnect or deletion SHALL atomically establish an authoritative tombstone, revoke approval and sessions, kill runs, cancel pending work, and prevent worker, command, recovery, and outbox paths from using the credential.

#### Scenario: Outbox delivery follows deletion
- **WHEN** a pending or replayed outbox item references a deleted credential
- **THEN** delivery is terminally suppressed and cannot authenticate to Topstep

### Requirement: Backup restoration preserves revocation
Backup and restoration procedures SHALL restore or reapply authoritative deletion/revocation state before execution is enabled and SHALL document retention of encrypted historical ciphertext without retaining plaintext secrets.

#### Scenario: Database backup predates disconnect
- **WHEN** an older backup is restored
- **THEN** operations reconcile deletion and revocation records before any credential-dependent command may run

### Requirement: Tester receives external revocation instruction
The application and offboarding runbook SHALL direct the tester to revoke the dedicated API key in TopstepX after testing or suspected compromise.

#### Scenario: Tester disconnects
- **WHEN** local deletion completes
- **THEN** the interface presents the external Topstep revocation step without displaying the deleted key

### Requirement: Deleted integration is terminal
The durable Topstep deletion transaction SHALL erase encrypted credential/session values, retain a privacy-preserving keyed tombstone and audit outcome, and SHALL NOT permit session refresh, replacement, duplicate onboarding, stale approval, worker restart, recovery, or outbox delivery to reactivate the integration.

#### Scenario: Deletion is retried
- **WHEN** the same tenant repeats deletion after the terminal commit
- **THEN** the operation succeeds idempotently, retains one tombstone, and creates no usable credential or approval

### Requirement: External epoch prevents restore resurrection
Hosted restoration SHALL require a deployment-controlled monotonic security epoch greater than the restored database epoch, and reconciliation SHALL revoke restored Topstep access before the database epoch advances.

#### Scenario: Backup predates deletion or revocation
- **WHEN** an operator restores the backup under a higher environment epoch
- **THEN** worker processing remains disabled, secrets and authorization are suppressed, and the tester must re-onboard

#### Scenario: Epoch is rolled back
- **WHEN** the configured environment epoch is less than the database epoch
- **THEN** startup/readiness and credential-dependent processing fail closed
