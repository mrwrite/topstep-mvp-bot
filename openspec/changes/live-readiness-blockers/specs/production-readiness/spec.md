## ADDED Requirements

### Requirement: Migration baseline repair
The project SHALL provide an Alembic migration baseline that can create a fresh production-like database without runtime `create_all()`.

#### Scenario: Fresh database migration
- **WHEN** migrations are applied to an empty database
- **THEN** all required application tables, indexes, and constraints are created successfully

### Requirement: Schema readiness blocks trading
The system SHALL block trading-sensitive actions when the database migration state is behind application head or schema checks fail.

#### Scenario: Database behind migration head
- **WHEN** readiness detects the database revision is behind migration head
- **THEN** readiness fails and live trading remains unavailable

### Requirement: Launch gate criteria
The system SHALL expose launch gate criteria that report pass/fail for all P0 live-readiness prerequisites.

#### Scenario: Launch gate has blocker
- **WHEN** any P0 criterion fails
- **THEN** the launch gate reports live trading unavailable and includes the blocking criteria

### Requirement: Controlled live flag remains disabled by default
The system SHALL require a separate explicit feature flag or allowlist in addition to passing launch gates before any controlled live trading can be considered.

#### Scenario: Launch gate passes but flag disabled
- **WHEN** all readiness gates pass but the live feature flag or allowlist is disabled
- **THEN** live trading remains blocked

### Requirement: Operational incident procedures
The project SHALL document operator procedures for disabling live mode, activating kill switches, running reconciliation, reviewing audit trails, restoring backups, and escalating incidents.

#### Scenario: Reconciliation incident occurs
- **WHEN** provider/app state mismatch blocks an account
- **THEN** the runbook tells operators how to inspect status, preserve audit context, and keep live trading disabled until resolved
