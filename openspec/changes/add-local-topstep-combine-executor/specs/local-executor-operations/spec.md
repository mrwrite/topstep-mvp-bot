## ADDED Requirements

### Requirement: Local runtime is interactive and loopback-only
The initial executor SHALL run in an interactive Windows or macOS user session, SHALL NOT install as an unattended service, and SHALL NOT accept non-loopback network connections. Any local HTTP control surface SHALL bind only to `127.0.0.1`, serve pinned local assets, validate Host and Origin, and require a per-launch anti-CSRF secret.

#### Scenario: Non-loopback binding is configured
- **WHEN** the executor is configured to bind to a LAN, public, wildcard, or non-loopback address
- **THEN** startup fails before credentials are loaded or provider access is attempted

#### Scenario: Remote origin calls the local control surface
- **WHEN** a request has an unapproved Host or Origin or lacks the per-launch secret
- **THEN** the local control surface rejects it without changing execution state

### Requirement: Known hosted and headless environments fail closed
Mutation-capable startup SHALL reject Railway, Vercel, CI, container, known cloud-hosted, service-role, and noninteractive execution indicators. An unsigned development override MUST NOT enable provider mutations.

#### Scenario: Executor starts inside CI
- **WHEN** CI or automated test environment indicators are present
- **THEN** only deterministic fake-provider or read-only test modes are available

### Requirement: Local journal integrity is verified
The executor SHALL store non-secret execution facts in a dedicated local SQLite database using foreign keys, WAL mode, schema migrations, user-only filesystem permissions, a single-writer lease, monotonic sequencing, and startup integrity checks. Provider mutations MUST remain disabled when schema, integrity, ownership, or lease validation fails.

#### Scenario: A second executor instance starts
- **WHEN** another live instance already owns the local writer lease
- **THEN** the second instance remains read-only and cannot authenticate or mutate provider state

#### Scenario: Migration is incomplete
- **WHEN** the local database is not at the supported schema revision
- **THEN** mutation-capable startup fails and reports a safe recovery instruction

### Requirement: Production executor artifacts are signed and version-bound
Every mutation-capable build SHALL verify a signed release manifest containing the executable hash, version, supported local schema range, and minimum policy version using an embedded release public key. Unsigned, modified, expired, revoked, or incompatible artifacts MUST remain mutation-disabled.

#### Scenario: Executable hash differs from the manifest
- **WHEN** startup detects that the installed artifact does not match the signed manifest
- **THEN** credentials are not loaded and provider mutations remain unavailable

### Requirement: Startup preflight is comprehensive and redacted
Before authentication or arming, preflight SHALL verify interactive local execution, loopback controls, supported signed version, clock synchronization, credential-store availability, database migrations/integrity, single-instance ownership, policy and consent bindings, exact-account state, rate configuration, provider reachability, and clean reconciliation. Reports MUST contain safe classifications rather than credentials or full provider identifiers.

#### Scenario: Clock skew exceeds policy
- **WHEN** measured clock skew is greater than the configured maximum
- **THEN** arming and mutations are denied until time health is restored

### Requirement: Logs and diagnostics contain no secrets
Local logs, crash diagnostics, telemetry, support bundles, and acceptance evidence MUST exclude credentials, provider tokens, full account IDs, custom tags, raw request headers, raw provider payloads, and personal information. Structured redaction SHALL apply before serialization, not only at display time.

#### Scenario: Provider exception contains request material
- **WHEN** an upstream exception includes an authorization header or provider payload
- **THEN** persisted diagnostics contain only a safe classification and local correlation identity

### Requirement: Updates fail safely and support rollback
Updates SHALL stop new entries, preserve and reconcile in-flight local state, verify the new signed artifact and schema compatibility, and require preflight before re-arming. Rollback SHALL refuse an executable that cannot read the current schema or policy and SHALL never reset execution state to a more permissive value.

#### Scenario: Update occurs after an ambiguous attempt
- **WHEN** an update is requested while an account reconciliation lock exists
- **THEN** the executor remains halted and the replacement version must reconcile the existing attempt before arming

### Requirement: Incident response prioritizes provider verification
The local incident procedure SHALL activate the local kill, stop new entries, reconcile or visibly classify open orders and positions, direct the user to verify TopstepX directly, revoke the dedicated API key when compromise is possible, preserve the journal, and prevent automatic re-arming.

#### Scenario: Local device is lost or suspected compromised
- **WHEN** the user reports loss or compromise of the personal device
- **THEN** operations direct immediate Topstep API-key revocation and the installation cannot be trusted or remotely re-enabled

### Requirement: Acceptance evidence is stage-specific
CI evidence, clean installation evidence, observe-only evidence, Practice qualification, first Combine order evidence, and automated Combine-session approval SHALL be recorded as separate stages. CI MUST use fakes and MUST NOT submit a real provider order. Sensitive values SHALL be redacted before evidence retention.

#### Scenario: Practice qualification passes
- **WHEN** all required Practice scenarios pass on the personal device
- **THEN** only the Practice gate is closed and the first Combine order remains separately unauthorized

### Requirement: Backup and uninstall preserve safe state
Local journal backup SHALL be explicit, local, integrity-checked, and documented as sensitive. Uninstall or reset SHALL require the executor to halt, surface unresolved provider state, remove OS-stored credentials only after confirmation, and instruct the user to revoke the Topstep key; deleting local state MUST NOT be treated as cancelling provider orders.

#### Scenario: User requests local data reset with an open reconciliation lock
- **WHEN** unresolved provider state exists during reset or uninstall
- **THEN** the operation warns and requires direct provider verification before destructive local cleanup
