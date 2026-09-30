## ADDED Requirements

### Requirement: Complete deletion lifecycle
Deletion SHALL support configured grace, cancellation during grace, legal holds, retention exceptions, session revocation, credential erasure, tenant-data deletion or anonymization, and retained audit evidence.

#### Scenario: Cancellation during grace
- **WHEN** the authenticated owner cancels a pending request before execution
- **THEN** deletion SHALL be cancelled and an audit event appended

#### Scenario: Legal hold
- **WHEN** a valid legal hold applies
- **THEN** execution SHALL remain blocked without restoring sessions or credentials

### Requirement: Tombstone-protected restore
Backups and restores SHALL honor durable deletion tombstones so deleted identity, sessions, and secrets cannot become usable after restore.

#### Scenario: Restore after deletion
- **WHEN** a backup predating deletion is restored
- **THEN** tombstones SHALL reapply deletion before the restored environment becomes usable

### Requirement: Repeatable deletion drill
A non-production drill SHALL produce JSON and Markdown evidence covering representative data, backup, deletion, purge/expiry, restore, and non-resurrection verification.

#### Scenario: Successful drill
- **WHEN** the documented drill completes
- **THEN** both reports SHALL show that identity, credentials, and sessions remain unusable after restore

### Requirement: TPM recovery-aware restore
Restored protected credentials SHALL remain unavailable until envelope integrity, deletion tombstones, recovery-wrap identity, and replacement-TPM rewrapping are verified and reconciled.

#### Scenario: Database backup without recovery custody
- **WHEN** an operator has a database backup but lacks the approved offline recovery ceremony and replacement TPM
- **THEN** the backup SHALL NOT be sufficient to decrypt credentials

### Requirement: Tenant-isolated lifecycle actions
Export, deletion request, cancellation, execution, revocation evidence, tombstones, and restore handling SHALL be scoped to the authenticated or explicitly authorized target tenant.

#### Scenario: Foreign deletion request identifier
- **WHEN** an authenticated tenant submits another tenant's deletion request ID for execution or cancellation
- **THEN** the system SHALL return the absent-request response and SHALL NOT revoke, anonymize, delete, restore, or emit work

#### Scenario: Revocation ownership mismatch
- **WHEN** a provider revocation attempt references a deletion request owned by a different tenant
- **THEN** the database SHALL reject the relationship

### Requirement: Hosted integration deletion suppresses durable work
Topstep disconnect and deletion SHALL make the integration non-executable before revoking sessions and approval, killing matching runs, cancelling commands, terminally suppressing outbox work, and erasing credential ciphertext; deletion SHALL retain one terminal keyed tombstone.

#### Scenario: Stale work follows Topstep deletion
- **WHEN** a worker, recovery scan, approval request, replacement request, or outbox delivery uses pre-deletion evidence
- **THEN** the terminal lifecycle and tombstone SHALL prevent credential use or integration resurrection
### Requirement: Hosted restored backups require an external epoch
A hosted database restore SHALL remain non-executable under an earlier security epoch until a disabled-worker operator reconciliation revokes restored access and advances the database epoch.

#### Scenario: Restored backup contains a formerly deleted integration
- **WHEN** the environment epoch is higher than the restored database epoch
- **THEN** old sessions, approvals, commands, and outbox work remain unusable and fresh onboarding is required
