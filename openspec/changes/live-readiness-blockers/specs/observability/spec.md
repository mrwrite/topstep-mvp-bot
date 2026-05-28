## ADDED Requirements

### Requirement: Queryable trade audit for readiness blockers
The system SHALL maintain queryable user-scoped audit events for context resolution, risk decisions, kill switch changes, order lifecycle transitions, duplicate suppression, retries, reconciliation, acknowledgements, and launch gate decisions.

#### Scenario: User reviews blocked live attempt
- **WHEN** a user's live attempt is blocked
- **THEN** the audit trail shows the context, risk, acknowledgement, and launch gate reasons without exposing secrets

### Requirement: Reconciliation observability
The system SHALL emit structured events and user/admin-visible status for reconciliation jobs, provider mismatches, unknown orders, and account lockouts.

#### Scenario: Reconciliation job finds mismatch
- **WHEN** a reconciliation job detects a mismatch
- **THEN** the system records an audit event, logs a redacted structured event, and marks the account as requiring reconciliation

### Requirement: Provider retry diagnostics
The system SHALL record retry decisions with provider error classification, retryability, correlation ids, and reconciliation result.

#### Scenario: Retry blocked
- **WHEN** retry is blocked because provider state is unknown
- **THEN** diagnostics explain that reconciliation is required and no duplicate live order was submitted

### Requirement: Launch gate audit
The system SHALL audit launch gate evaluations and changes to any live-enabling flag, allowlist, acknowledgement version, or risk policy that affects live readiness.

#### Scenario: Live feature flag changes
- **WHEN** an operator changes a live-enabling flag or allowlist
- **THEN** the system records actor, timestamp, previous value, new value, and reason
