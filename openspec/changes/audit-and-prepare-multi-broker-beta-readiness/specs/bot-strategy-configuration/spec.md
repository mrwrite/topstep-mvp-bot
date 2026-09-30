## ADDED Requirements

### Requirement: Versioned configuration
The system SHALL store immutable activated configuration versions binding tenant, environment, broker account, instruments, market sessions, data source, strategy version, parameters, schedule, risk policy, and notification settings. Editing an active configuration MUST create a draft version.

#### Scenario: User changes active threshold
- **WHEN** a user changes an RSI threshold on an active configuration
- **THEN** the running snapshot remains unchanged and a new draft requiring validation and activation is created

### Requirement: Strategy validation and rationale
The initial beta SHALL support `rsi-threshold-v1` without changing its verified default behavior. Parameters MUST be schema-validated and each evaluated bar MUST produce a rationale containing inputs, indicator values, data-quality result, signal, and guardrail decision.

#### Scenario: Invalid or malicious parameters
- **WHEN** a draft contains out-of-range thresholds, unknown fields, executable content, oversized input, or contradictory values
- **THEN** validation rejects the draft without executing user content and records safe field-level errors

### Requirement: Market-session correctness
Schedules SHALL use provider instrument calendars and named exchange time zones, handle holidays and daylight-saving changes, and fail closed when the clock offset or calendar is unknown.

#### Scenario: Bot reaches a closed session
- **WHEN** a scheduled evaluation occurs outside the verified instrument session
- **THEN** no entry order is created and the audit rationale identifies the session gate
