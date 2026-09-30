## ADDED Requirements

### Requirement: Controlled Fernet migration
The system SHALL inventory, dry-run, back up, idempotently migrate, verify, and reconcile every active Fernet record before envelope-only cutover.

#### Scenario: Interrupted migration
- **WHEN** concurrent workers, duplicate commands, or a crash occur before or after a migration commit
- **THEN** PostgreSQL-backed retry SHALL resume safely and preserve one authoritative envelope per record

### Requirement: Explicit envelope-only cutover
Legacy Fernet reads SHALL be permitted only during the declared migration window and SHALL be rejected after verified envelope-only cutover.

#### Scenario: Legacy ciphertext after cutover
- **WHEN** runtime receives Fernet ciphertext after cutover
- **THEN** it SHALL reject the value without silently loading a legacy or development key

### Requirement: Legacy-key retirement controls
The runtime Fernet key SHALL be removed immediately after verified cutover, while encrypted rollback material remains offline for 30 days by default and destruction requires explicit owner approval.

#### Scenario: Destruction requested
- **WHEN** an operator proposes destroying legacy rollback material
- **THEN** the system SHALL require exact target identity, zero active dependencies, verified backup/recovery evidence, approval, and documented rollback implications
