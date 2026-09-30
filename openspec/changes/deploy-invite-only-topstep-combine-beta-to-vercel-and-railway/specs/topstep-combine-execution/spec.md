## ADDED Requirements

### Requirement: Durable worker is sole provider executor
Only the fenced Railway worker SHALL perform provider-side Trading Combine execution, and each attempt SHALL carry tenant, user, integration, approved account, run, command, and fencing identities.

#### Scenario: API restarts during an active run
- **WHEN** the Railway API restarts while the worker holds a valid fenced lease
- **THEN** authoritative execution remains database-owned and no HTTP lifecycle assumes ownership

### Requirement: Simulated-only provider boundary
All contract and market selection SHALL explicitly use `live: false`; the system MUST reject Express Funded, Live Funded, live accounts, live-provider invocation, and any account without current exact approval.

#### Scenario: Live invocation requested
- **WHEN** any client, command, or provider path requests live execution
- **THEN** the server rejects it before a provider order can be submitted

### Requirement: Approval and risk revalidation
The worker SHALL revalidate credential state, ownership, attestation, approval, dry-run evidence, server-controlled risk policy, freshness, reconciliation state, and all kill switches before run start and before every provider submission.

#### Scenario: Approval revoked before submission
- **WHEN** approval is revoked after evaluation but before provider submission
- **THEN** the proposed order is not sent and the run stops safely

### Requirement: Ambiguous outcome reconciliation
Order intent, submission attempt, provider acknowledgement, fills/trades, positions, and ledger entries SHALL be separate durable records, and an ambiguous submission MUST be reconciled with provider state before retry.

#### Scenario: Submission times out
- **WHEN** provider acknowledgement is lost after a submission attempt
- **THEN** the worker does not silently retry, fabricate a fill, switch accounts, or fall back to internal simulation

### Requirement: Conservative first-tester policy
The server SHALL enforce one tester, one tenant, one approved account, quantity one, explicit instrument and strategy allowlists, position/order/loss/freshness/schedule/cooldown limits, and global, tenant, account, and run kills that the browser cannot relax.

#### Scenario: Browser requests a higher quantity
- **WHEN** the browser submits quantity greater than one or a disallowed instrument or strategy
- **THEN** the server rejects the request before durable provider intent is authorized

### Requirement: Read-only dry run and explicit consent
Provider submission SHALL remain disabled until the tester has explicitly accepted the Combine consequences and a current dry run has exercised authentication, ownership, simulated contracts/market data, signals, proposed orders, risks, and kills without submitting an order.

#### Scenario: Dry run has not passed
- **WHEN** otherwise valid automated execution is requested without current successful dry-run evidence and consent
- **THEN** no provider order is submitted

### Requirement: Hosted risk policy is server-owned and versioned
The hosted Combine beta SHALL require an active policy bound to the tenant, tester, cohort, Topstep integration, and exact approved provider account. The policy MUST contain non-empty strategy/version and instrument allowlists, explicit quantity/position/order/loss/freshness/schedule/cooldown limits, current effective and expiration times, and `provider_order_execution_enabled=false`. Browser input MUST NOT create, alter, or relax policy values. A policy change MUST increment its version and require purpose-bound operator approval; every new policy version invalidates prior dry-run consent.

#### Scenario: Risk policy is missing or incomplete
- **WHEN** a tester requests consent or a hosted dry run without a complete active server policy
- **THEN** the request is denied and no proposal or provider operation is created

#### Scenario: Relaxed quantity policy is submitted
- **WHEN** an operator submits a hosted beta policy permitting more than one contract
- **THEN** the policy is rejected and provider order execution remains disabled

### Requirement: Versioned tester consent
The tester SHALL accept the current consent text version bound to the tenant, tester, integration, credential generation, approved account, risk policy, and correlation ID before dry-run work is queued. The consent MUST explain the simulated Combine consequences and must not purport to waive security obligations.

#### Scenario: Policy version changes
- **WHEN** an operator publishes a different risk-policy version
- **THEN** consent tied to a prior policy version cannot authorize a dry run

### Requirement: Durable isolated dry-run evaluation
Hosted dry-run requests SHALL be idempotent database records processed only by a durable leased/fenced worker. Each request MUST bind the current approval, credential generation, security epoch, policy, consent, strategy/configuration, and tenant-owned persisted market input. Risk outcomes SHALL be persisted as individual safe classifications. Dry-run proposals SHALL use a separate table and a fixed `dry_run_only` state, have no provider order identity, and MUST NOT mutate order, fill, position, balance, fee, ledger, or realized-P&L records.

#### Scenario: Worker retries a dry run
- **WHEN** a worker retries after a lease expires or an acknowledgement is lost
- **THEN** the stable identity/fence prevents duplicate evaluations and proposals

#### Scenario: Read-only provider or reconciliation evidence is unavailable
- **WHEN** durable Topstep market-data or provider reconciliation readiness cannot be verified
- **THEN** the dry run is marked degraded and does not create an actionable proposal

#### Scenario: Client submits policy overrides
- **WHEN** a dry-run request includes risk values or configuration intended to relax the server policy
- **THEN** those values are rejected or ignored and the persisted policy remains authoritative

### Requirement: Provider mutations are unavailable in the hosted beta
The hosted Topstep adapter and startup configuration SHALL advertise read-only capabilities only and MUST fail closed for place, cancel, modify, close-position, partial-close, and live-data/account operations.

#### Scenario: Mutation method is invoked
- **WHEN** a hosted code path attempts a Topstep mutation
- **THEN** the adapter rejects it before any provider network request
