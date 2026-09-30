## ADDED Requirements

### Requirement: Configured cohort and suspension controls
Production simulation beta SHALL require explicit cohort cap, eligibility, support ownership, incident escalation, retention, maintenance, and suspension configuration, and missing required values SHALL block admission.

#### Scenario: Critical incident
- **WHEN** an active critical incident or beta suspension is recorded
- **THEN** new admissions and new runs SHALL be blocked while safe stop/export/support remain available

### Requirement: Health and degraded behavior
The system SHALL expose user-visible health and last-good timestamps and SHALL fail closed for degraded secret, database, execution-owner, risk, or market-data state.

#### Scenario: Lease health degraded
- **WHEN** a running simulation cannot renew its lease
- **THEN** the user SHALL see degraded/recovering state and no stale owner SHALL continue

### Requirement: Feedback and abuse handling
The system SHALL provide tenant-scoped support/feedback intake, invite revocation, and auditable suspension without exposing cross-tenant data.

#### Scenario: Invite revoked
- **WHEN** an invite or beta access is revoked
- **THEN** new simulation runs SHALL be denied and the outcome SHALL be auditable

### Requirement: TPM and recovery operations
Operations SHALL maintain approved provisioning, inventory, rotation, Fernet cutover, backup/restore, replacement recovery, lost/stolen Pi, TPM failure/lockout, recovery compromise, and retirement procedures.

#### Scenario: Destructive key action
- **WHEN** an operator requests TPM-key eviction or legacy/recovery material destruction
- **THEN** the action SHALL require exact target identity, dependency inventory, successful backup/recovery evidence, explicit approval, and documented rollback implications

### Requirement: Hosted Combine operations
Operations SHALL maintain separate Vercel frontend and Railway API/worker/PostgreSQL/Redis deployment, migration, readiness, backup/restore, origin, secret rotation, provider incident, kill, disconnect, tester offboarding, and rollback procedures.

#### Scenario: Hosted acceptance evidence is unavailable
- **WHEN** deployment credentials, tester credentials, or controlled provider evidence are unavailable
- **THEN** external tasks SHALL remain open and local software tests SHALL NOT be represented as deployment or provider evidence
### Requirement: Hosted restore ceremony is fail-closed
The operator SHALL increment the non-secret hosted security epoch before restored services process work, keep provider execution and workers disabled during reconciliation, and retain redacted correlation-bound evidence.

#### Scenario: Reconciliation is interrupted
- **WHEN** suppression or epoch advancement fails
- **THEN** readiness remains degraded and credential-dependent execution stays disabled until idempotent reconciliation completes
