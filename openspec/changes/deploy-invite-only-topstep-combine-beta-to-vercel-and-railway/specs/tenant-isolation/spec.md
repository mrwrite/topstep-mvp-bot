## ADDED Requirements

### Requirement: Provider resources are tenant-bound
Credentials, discovery snapshots, attestations, approvals, sessions, commands, provider records, risk state, and deletion tombstones SHALL be bound to the owning tenant, user, and integration with server-derived authorization.

#### Scenario: Cross-tenant account substitution
- **WHEN** a user supplies another tenant's integration, account, approval, run, or command identifier
- **THEN** access fails without revealing whether the foreign resource exists

### Requirement: One-account cohort enforcement
The initial cohort SHALL permit only the single approved tenant and exact provider account, and account switching SHALL require a new discovery, attestation, approval, and dry run.

#### Scenario: Another owned account is selected
- **WHEN** the same credential owns another active provider account
- **THEN** that ownership alone does not authorize execution

### Requirement: Database-enforced Topstep tenant relationships
Topstep credentials, sessions, snapshots, discovered accounts, attestations, approvals, and tombstones SHALL use tenant-inclusive parent relationships and tenant-leading indexes, and PostgreSQL SHALL reject a child referencing another tenant's integration or evidence.

#### Scenario: Cross-tenant relationship is inserted directly
- **WHEN** application or stale-worker code attempts to persist a Topstep child under a foreign tenant parent
- **THEN** the database rejects the transaction and preserves authoritative state
