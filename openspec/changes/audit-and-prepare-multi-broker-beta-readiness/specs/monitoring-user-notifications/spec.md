## ADDED Requirements

### Requirement: Safety and reliability telemetry
The system SHALL measure service health, market-data age, clock offset, worker leases, provider connectivity, token refresh, rate budgets, order-state age, unknown submissions, reconciliation drift, risk lockouts, kill-switch latency, and notification delivery.

#### Scenario: Market data becomes stale
- **WHEN** quote or bar age exceeds the configured threshold
- **THEN** new entries are blocked, the service and affected bot show degraded status, and an alert includes tenant-safe correlation data

### Requirement: User-visible operational states
Users SHALL see healthy, degraded, paused, reconciling, and incident-blocked states with the affected account, last-known-good timestamp, trading impact, and safe next action.

#### Scenario: Broker disconnects
- **WHEN** the broker stream disconnects beyond the tolerated interval
- **THEN** the bot pauses new entries, the UI updates without claiming normal operation, and recovery requires health and reconciliation checks

### Requirement: Actionable notifications
The system SHALL support user and operator notifications for authentication changes, connection expiry/revocation, bot transitions, order rejection/unknown state, risk lockout, kill switch, reconciliation conflict, and incidents with deduplication and delivery status.

#### Scenario: Duplicate incident signals arrive
- **WHEN** repeated provider failures map to the same incident key
- **THEN** notifications are deduplicated within policy while counters and the latest state continue to update
