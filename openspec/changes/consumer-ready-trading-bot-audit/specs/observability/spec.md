## ADDED Requirements

### Requirement: Structured application logging
The backend SHALL emit structured logs with request id, user id where safe, provider, integration id, account id, order id, session id, severity, and redacted error context.

#### Scenario: Provider call fails
- **WHEN** a provider API call fails
- **THEN** the system logs a structured redacted event with correlation identifiers and error classification

### Requirement: Trade audit trail
The system SHALL maintain a queryable append-only audit trail for all trade-related user, strategy, risk, provider, and system actions.

#### Scenario: User reviews trade history
- **WHEN** a user views trade audit history
- **THEN** the system shows only that user's scoped audit events with order lifecycle and risk decision details

### Requirement: Health and readiness checks
The backend SHALL expose liveness, readiness, database, migration, and provider diagnostic health endpoints with appropriate authentication for sensitive details.

#### Scenario: Database is unavailable
- **WHEN** the readiness endpoint checks the database and cannot connect
- **THEN** readiness fails and deployment health does not mark the service ready for trading

### Requirement: Provider API diagnostics
The system SHALL expose provider diagnostics for credential status, auth/session status, account availability, contract availability, rate limits where available, and latest provider errors.

#### Scenario: Provider credentials fail
- **WHEN** stored provider credentials are invalid
- **THEN** diagnostics show an authentication failure without exposing secret values

### Requirement: User-visible trading status
The frontend SHALL display user-visible readiness and runtime status for provider health, account status, market data freshness, risk lockouts, bot session state, and order state.

#### Scenario: Risk lockout active
- **WHEN** an account is risk-locked
- **THEN** the dashboard shows the lockout reason and disables new trading actions

### Requirement: Admin and support diagnostics
The system SHALL provide admin-only diagnostic views or exports for investigating failed orders, provider errors, bot sessions, and audit trails without exposing credentials.

#### Scenario: Support investigates failed order
- **WHEN** an admin reviews a failed order
- **THEN** the admin can see correlated request, risk, provider, and audit events with secrets redacted
