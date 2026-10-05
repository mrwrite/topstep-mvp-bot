## ADDED Requirements

### Requirement: Hosted services are outside the order causal chain
Railway, Vercel, hosted PostgreSQL, Redis, hosted workers, and hosted browser assets SHALL be limited to read-only administration, support, monitoring, and sanitized telemetry. They MUST NOT originate or transmit signals, schedules, configuration changes, approvals, feature flags, commands, or payloads capable of causing a local provider mutation.

#### Scenario: Hosted service publishes an order-capable payload
- **WHEN** a hosted component attempts to publish an instrument, side, quantity, trigger time, or other executable instruction to a device
- **THEN** the operation is rejected and no local delivery channel exists

### Requirement: Telemetry transport is outbound-only
The local executor MAY initiate authenticated HTTPS telemetry uploads to Railway. Railway responses SHALL contain only an acknowledgement identity and retry timing, and the executor SHALL reject or ignore all other response fields. No hosted polling, WebSocket, SSE, push, callback, or command channel to the executor is permitted.

#### Scenario: Telemetry response includes configuration
- **WHEN** Railway returns policy, strategy, account, order, kill, or configuration content with an acknowledgement
- **THEN** the local executor ignores the content and records a protocol violation

### Requirement: Telemetry uses an explicit data allowlist
Telemetry schemas SHALL allow only coarse health, executable/configuration versions, timestamps, hashed installation and account correlation identifiers, safe order-lifecycle classifications, sanitized positions, fills, P&L, risk outcomes, and audit classifications. Full account IDs, usernames, credentials, tokens, custom tags, raw provider payloads, local database contents, and strategy secrets MUST be rejected before transmission and ingestion.

#### Scenario: Disallowed field is serialized
- **WHEN** an outbound event contains a full account ID, credential, token, custom tag, or raw provider response
- **THEN** local serialization fails closed and nothing from that event is transmitted

### Requirement: Hosted projections are non-authoritative
Hosted telemetry records SHALL be immutable observations or derived read-only projections and MUST NOT determine local strategy, policy, consent, lifecycle, kill, reconciliation, or provider state. Hosted deletion or corruption cannot cause a local provider mutation.

#### Scenario: Hosted projection disagrees with the local journal
- **WHEN** Railway displays an order, position, or risk state different from the local provider reconciliation
- **THEN** the executor retains local/provider authority and reports telemetry drift without changing execution state from hosted data

### Requirement: Telemetry failure follows local policy
Telemetry outage, rejection, or backpressure SHALL never enable or trigger an order. The local policy SHALL either halt new entries immediately or permit a bounded offline interval with a bounded local outbox; exhaustion or expiry SHALL halt new entries.

#### Scenario: Railway is unavailable
- **WHEN** outbound telemetry cannot be acknowledged
- **THEN** events are handled according to the current local fail-closed policy and no remote fallback or command channel is created

### Requirement: Hosted Topstep credentials and execution are retired
Hosted Topstep credential onboarding, session custody, order controls, and provider execution surfaces SHALL be removed or return a permanent `local_executor_required` classification. Any previously stored hosted Topstep credential SHALL be tombstoned and deleted, and the user SHALL be instructed to rotate the dedicated API key before local qualification.

#### Scenario: User submits a Topstep key to Railway
- **WHEN** an authenticated client calls a legacy hosted Topstep credential endpoint
- **THEN** Railway refuses the secret without persisting or forwarding it and directs the user to the local executor

### Requirement: Telemetry credentials cannot access Topstep
The device telemetry credential SHALL be independently generated, narrowly scoped to telemetry ingestion for one installation, revocable, and unusable for Topstep authentication, hosted administration, or retrieval of another installation's data.

#### Scenario: Telemetry credential is presented to an administrative endpoint
- **WHEN** the device credential is used outside its ingestion scope
- **THEN** authorization fails without disclosing protected resources

### Requirement: Hosted dashboard clearly reports its limitations
The hosted user interface SHALL label data as delayed/read-only, identify the last acknowledged device event, and state that order placement, cancellation, position closing, policy changes, and emergency control occur only on the personal device.

#### Scenario: Local device is offline
- **WHEN** telemetry freshness exceeds the configured display threshold
- **THEN** the dashboard prominently reports the device as stale and does not offer an execution control

