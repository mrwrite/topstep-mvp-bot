## ADDED Requirements

### Requirement: Idempotent order intent
The system SHALL persist each immutable order intent before submission and enforce tenant, environment, account, and client-order-id uniqueness. Retrying a command MUST return the original result or a conflict; it MUST NOT create a duplicate order.

#### Scenario: Worker restarts after submission timeout
- **WHEN** a worker cannot determine whether the broker accepted an order
- **THEN** the order enters `SUBMISSION_UNKNOWN`, the account is locked for new entries, and reconciliation occurs before any resubmission decision

### Requirement: Complete lifecycle and fill accounting
The system SHALL model submitted, accepted, rejected, partially filled, filled, cancel-pending, canceled, replace-pending, replaced, expired, unknown, and manual-review states as supported by each provider. Positions, balances, and P&L MUST derive from fills and broker snapshots, never submission alone.

#### Scenario: Partial fill then cancel
- **WHEN** a broker reports a partial fill followed by cancellation
- **THEN** cumulative filled quantity remains posted to the position and ledger, the unfilled remainder is canceled, and the order is not shown as fully filled

### Requirement: Deterministic reconciliation
Reconciliation SHALL compare local orders, fills, positions, and balances with provider state at startup, reconnect, event gaps, unknown outcomes, and scheduled intervals. Conflicts MUST be classified, audited, and either deterministically repaired or locked for review; they MUST NOT be silently overwritten.

#### Scenario: Broker position differs from local projection
- **WHEN** reconciliation finds an unexplained position difference
- **THEN** new entries are blocked for the account, both values are preserved as evidence, and an operator/user resolution workflow is created
