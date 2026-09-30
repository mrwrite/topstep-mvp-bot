## ADDED Requirements

### Requirement: Persisted simulation state machine
Simulation runs SHALL persist state and version and SHALL permit only defined transitions among Requested, Starting, Running, Pausing, Paused, Stopping, Stopped, Failed, Killed, and Recovering.

#### Scenario: Invalid transition
- **WHEN** a command requests a transition not valid from the persisted state
- **THEN** the command SHALL be rejected and recorded without changing the run

### Requirement: Fenced durable leases
Run ownership SHALL use expiring durable leases with monotonically increasing fencing tokens, and stale owners MUST NOT checkpoint, transition, or emit execution intent.

#### Scenario: Lease takeover
- **WHEN** a lease expires and another worker acquires it
- **THEN** the new worker SHALL receive a higher fence and activity from the old fence SHALL be rejected

### Requirement: Atomic commands and outbox
Commands SHALL be tenant-scoped and idempotent, and committed execution intent/state changes SHALL atomically create durable outbox events consumed idempotently with bounded retries and terminal failure evidence.

#### Scenario: Crash after commit
- **WHEN** a worker crashes after committing state and an outbox event but before publication
- **THEN** another worker SHALL publish the committed event exactly once effectively

#### Scenario: Duplicate delivery
- **WHEN** an outbox event is delivered more than once to a consumer
- **THEN** only one effective consumer outcome SHALL be recorded

### Requirement: Safe recovery and kill handling
Recovery SHALL reacquire a fenced lease, check durable kill and reconciliation state, and MUST NOT create an order solely because recovery occurred.

#### Scenario: Kill during recovery
- **WHEN** a kill switch is active while a run is Recovering
- **THEN** the run SHALL transition to Killed and no new simulated order SHALL be submitted

### Requirement: Durable command control plane
Every beta-reachable start, pause, resume, stop, and kill operation SHALL derive its tenant from authenticated server context, persist an idempotent command, transition authoritative database state, and emit outbox work in the same transaction.

#### Scenario: Concurrent starts for one scope
- **WHEN** two start requests race for the same tenant/account/instrument scope
- **THEN** database serialization and uniqueness SHALL permit only one active run

#### Scenario: Command acceptance
- **WHEN** a valid control command is accepted
- **THEN** the response SHALL identify both the command and current run state without claiming completion until the command has a terminal outcome

### Requirement: Fenced execution effects
Every worker checkpoint, simulated order, simulated fill, ledger mutation, and execution outbox event MUST match the active tenant, run, lease owner, and fencing token.

#### Scenario: Expired owner returns
- **WHEN** a worker with an older fence attempts an execution effect after takeover
- **THEN** the write SHALL fail before any domain effect commits

### Requirement: Recoverable outbox claims
Outbox events SHALL have stable identities and expiring claims, SHALL allow redelivery, and SHALL record consumer success only in the same transaction as durable consumer effects.

#### Scenario: Crash before acknowledgement
- **WHEN** a consumer transaction does not commit
- **THEN** the expired claim SHALL be reclaimable and idempotent effects SHALL prevent duplication

### Requirement: Stable durable market inputs
Every automated simulation input SHALL have a stable source identity and a
separate content digest, and the fenced worker SHALL classify duplicate, stale,
out-of-order, conflicting, missing-predecessor, and too-old input before
strategy evaluation.

#### Scenario: Conflicting committed identity
- **WHEN** the same source identity arrives with different content
- **THEN** the run SHALL fail or remain explicitly degraded and SHALL emit no new order

#### Scenario: Duplicate input after restart
- **WHEN** a committed market input is redelivered after worker replacement
- **THEN** the existing evaluation SHALL be returned without another economic effect

### Requirement: Atomic fenced evaluation effects
Automated evaluation effects SHALL share one fenced authority. Signal, risk
decision, simulated submission, simulated fill, position, account, ledger,
risk-counter, outbox, and checkpoint changes SHALL
share one fenced authority and MUST be committed in one transaction or
represented by explicit durable intent.

#### Scenario: Crash before checkpoint commit
- **WHEN** the worker process terminates after constructing economic effects but before commit
- **THEN** none of those effects SHALL be visible and the input SHALL remain recoverable

### Requirement: Integrity-protected complete checkpoints
Every evaluation checkpoint SHALL contain market, evaluation, strategy,
configuration, clock, risk, position, account, ledger, intent, event, and
freshness state and SHALL carry a canonical integrity digest.

#### Scenario: Checkpoint tampering
- **WHEN** checkpoint content no longer matches its digest
- **THEN** recovery SHALL transition the run to Failed without evaluating or repairing financial state

### Requirement: Verified tenant worker context
Durable discovery MAY identify work across tenants only in explicitly named worker maintenance scopes, and every command, recovery, market, and outbox effect MUST establish a verified tenant job context before touching tenant data.

#### Scenario: Environment-substituted worker job
- **WHEN** a signed job from another environment is delivered to the worker
- **THEN** validation SHALL reject it before lease, state, checkpoint, order, fill, ledger, or delivery mutation
### Requirement: Hosted credential work is epoch-bound
Credential-dependent hosted runs, commands, jobs, and outbox records SHALL carry tenant, integration, credential generation, security epoch, stable identity, and correlation/causation evidence and SHALL be revalidated before side effects.

#### Scenario: Old work is claimed after restore
- **WHEN** the work epoch or credential generation is no longer current
- **THEN** the worker cancels or terminally suppresses it without provider authentication
