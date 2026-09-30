## ADDED Requirements

### Requirement: Mandatory tenant context
Every tenant-owned repository, route, job, report, export, reconciliation operation, simulation command, and deletion operation SHALL require a validated tenant context that is not independently authorized by a client-supplied tenant identifier.

#### Scenario: Missing tenant context
- **WHEN** tenant-owned code is invoked without validated tenant context
- **THEN** it SHALL fail closed before querying or mutating tenant data

#### Scenario: Cross-tenant identifier
- **WHEN** a user supplies another tenant's resource identifier
- **THEN** the system SHALL deny access using the same response as a nonexistent resource

### Requirement: Verified background tenant identity
Background work SHALL persist and validate tenant identity and SHALL reject missing, malformed, or stale tenant job envelopes.

#### Scenario: Forged job tenant
- **WHEN** a worker receives a job whose tenant identity does not match the durable command
- **THEN** the worker SHALL reject it and record a redacted audit event

### Requirement: Structural enforcement
CI SHALL include an architectural tenant-scope check covering beta-reachable routes, services, repositories, jobs, analytics, and operator tools.

#### Scenario: New unscoped query
- **WHEN** new beta-reachable code directly queries a tenant-owned model outside an approved tenant repository
- **THEN** the architectural check SHALL fail

### Requirement: Tenant-scoped durable execution
Run reads, commands, leases, checkpoints, outbox consumption, status streams, and kill operations SHALL require matching authenticated or verified-job tenant context.

#### Scenario: Cross-tenant run identifier
- **WHEN** a user submits another tenant's run ID to any control or status path
- **THEN** the response SHALL be indistinguishable from a nonexistent run and no command or effect SHALL be created

#### Scenario: Cross-tenant market input
- **WHEN** a tenant queues or processes market input for another tenant's run
- **THEN** the operation SHALL fail as not found before an evaluation or economic effect is created

### Requirement: Immutable trusted-context contract
Request tenant context SHALL originate only after validated authentication,
background context SHALL originate only from a verified versioned envelope, and
operator context SHALL be actor-, purpose-, case-, target-, action-, and
expiry-bound. Context MUST NOT be replaced by a client field.

#### Scenario: Conflicting context
- **WHEN** an operation attempts to replace its bound tenant with a different client or internal tenant identifier
- **THEN** the system SHALL reject the replacement before querying and SHALL record only a safe failure classification

#### Scenario: Newly authorized operator target
- **WHEN** an authorized operator supplies valid purpose, case, action, target, and unexpired approval context
- **THEN** the system SHALL create a short-lived target tenant context for that operation and SHALL retain the operator as actor

### Requirement: Non-escaping tenant repository
The beta request persistence port SHALL require tenant context for construction,
SHALL apply tenant predicates internally to reads, writes, locks, aggregates,
pagination, and bulk operations, and MUST NOT return a raw ORM session or query.

#### Scenario: Cross-tenant bulk mutation
- **WHEN** a scoped caller executes a bulk update or delete while only another tenant has matching rows
- **THEN** zero rows SHALL change and no outbox work SHALL be emitted

#### Scenario: Cross-tenant object flush
- **WHEN** a context-bound session contains a new, dirty, or deleted object owned by another tenant
- **THEN** flush SHALL fail before the database mutation commits

### Requirement: Complete signed job context
Every tenant job envelope SHALL authenticate tenant, actor, stable job identity,
job type, purpose, issuer, environment, issue and expiry, correlation and
causation, payload digest, nonce, and format version. Consumers SHALL compare
the expected durable-record values before processing.

#### Scenario: Substituted job field
- **WHEN** tenant, actor, job type, purpose, issuer, environment, job identity, or payload differs from the signed and expected value
- **THEN** the job SHALL be rejected without disclosing whether its target exists

#### Scenario: Idempotent replay
- **WHEN** a valid job envelope for an already committed durable identity is redelivered
- **THEN** repository uniqueness and consumer idempotency SHALL return the existing outcome without a second economic effect

### Requirement: Tenant-safe status and streams
Every polling or streaming status path SHALL authenticate and verify tenant
ownership before initial retrieval and on reconnect, SHALL read durable state,
and MUST NOT use a shared unscoped in-memory channel.

#### Scenario: Foreign SSE run
- **WHEN** a tenant subscribes to another tenant's durable run identifier
- **THEN** the endpoint SHALL return the same 404 shape as an absent run and SHALL emit no status event

### Requirement: Tenant-inclusive indirect relationships
Tenant-owned delivery acknowledgement and provider-revocation records SHALL
carry non-null tenant identity and SHALL be database-constrained to a parent
record with the same tenant where supported.

#### Scenario: Mismatched delivery tenant
- **WHEN** a delivery acknowledgement identifies a tenant different from its outbox event
- **THEN** PostgreSQL SHALL reject the relationship and no acknowledgement SHALL persist

### Requirement: Hosted provider authorization is generation-bound
Topstep credentials, sessions, discovery snapshots, discovered accounts, attestations, approvals, and tombstones SHALL carry tenant identity and tenant-inclusive parent constraints, and the authorization decision SHALL require the current credential generation.

#### Scenario: Prior-generation approval is replayed
- **WHEN** a stale client, operator request, worker, or restored row presents an approval from a replaced credential generation
- **THEN** eligibility SHALL deny it and no provider action SHALL occur
