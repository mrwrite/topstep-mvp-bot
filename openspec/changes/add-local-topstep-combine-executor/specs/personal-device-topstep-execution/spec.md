## ADDED Requirements

### Requirement: Personal device is the sole mutation authority
Topstep order placement, modification, cancellation, and position-close operations SHALL execute only inside the interactive local executor running on the trader's personal device. Hosted APIs, hosted workers, hosted schedulers, webhooks, remotely served browser code, and telemetry services MUST NOT invoke or relay provider mutations.

#### Scenario: Hosted process attempts a provider mutation
- **WHEN** a Railway API or worker imports or invokes a mutation-capable Topstep client
- **THEN** startup or architecture verification fails before any provider request is sent

#### Scenario: Local executor submits an approved mutation
- **WHEN** the interactive local executor has passed every current execution gate and submits an approved mutation
- **THEN** the Topstep request originates directly from the personal-device process

### Requirement: Hosted adapter remains read-only
The existing hosted Topstep adapter SHALL continue to advertise read-only capabilities and SHALL reject place, modify, cancel, close, partial-close, and other provider mutation methods before network I/O.

#### Scenario: Hosted mutation flag is enabled
- **WHEN** a hosted environment attempts to enable provider mutations through configuration
- **THEN** the hosted service fails closed and does not become order capable

### Requirement: Local credentials never enter hosted custody
The local executor SHALL obtain the Topstep username and dedicated API key through a local interaction, store the API key only through an approved operating-system credential store, and keep provider session tokens in local process memory. Credentials and tokens MUST NOT be uploaded to Railway, Vercel, telemetry, hosted logs, command-line arguments, configuration files, SQLite, or browser storage.

#### Scenario: Executor restarts
- **WHEN** the local process restarts after a provider session existed
- **THEN** it retrieves the API key from the operating-system credential store and creates a new session without reading a persisted token

#### Scenario: Telemetry is serialized
- **WHEN** any local execution event is prepared for hosted telemetry
- **THEN** schema validation rejects usernames, API keys, provider tokens, and raw provider request or response bodies

### Requirement: Simulated provider boundary is explicit
Every local contract search and history request SHALL send `live: false`. The local executor MUST reject any live-data or live-account provider path and MUST bind mutations to one exact locally approved simulated account ID.

#### Scenario: Live provider selection is requested
- **WHEN** configuration, UI input, or provider data requests `live: true` or a live-provider path
- **THEN** the executor rejects the request before authentication or mutation

#### Scenario: A different owned account is selected
- **WHEN** the provider returns another account owned by the same credential
- **THEN** that account remains unauthorized until the complete account-change and re-arming ceremony succeeds

### Requirement: Strategy causation remains local
Market acquisition, strategy evaluation, proposed-order creation, and the final risk decision SHALL occur locally from versioned local inputs. The executor MUST NOT accept an order, signal, strategy trigger, schedule trigger, or mutation-capable configuration from Railway, Vercel, webhooks, push channels, or a remote browser bundle.

#### Scenario: Hosted signal is received
- **WHEN** a hosted payload contains an order side, quantity, contract, trigger, or instruction capable of causing a provider action
- **THEN** the local executor rejects and records the payload as a prohibited remote instruction

### Requirement: Provider actions use a durable local journal
Before any provider mutation, the executor SHALL commit an immutable local intent and a distinct submission-attempt boundary containing stable identity, exact account, contract, side, type, quantity, strategy/configuration versions, policy version, risk decision, and a unique provider `customTag`. Acknowledgement, provider order, trade, position, and reconciliation facts SHALL be stored separately.

#### Scenario: Process stops before network transmission
- **WHEN** the executor stops after committing an intent but before committing a submission attempt
- **THEN** restart recovery classifies the intent as not submitted and does not infer a provider order

#### Scenario: Process stops after transmission begins
- **WHEN** the executor stops after committing a submission attempt but before committing an acknowledgement
- **THEN** restart recovery classifies the attempt as ambiguous and reconciles provider state before any retry

### Requirement: Ambiguous submissions are reconciled before retry
A timeout, connection loss, pending response, unknown response, lost acknowledgement, or crash after the attempt boundary SHALL create an account-level reconciliation lock. The executor SHALL compare provider order history, stable `customTag`, immutable order fields, trades, positions, and local facts, and MUST NOT automatically repeat order placement until exactly one authoritative outcome is established.

#### Scenario: Exactly one matching provider order is found
- **WHEN** reconciliation finds one provider order matching the stable tag and immutable intent
- **THEN** the executor links that order to the existing intent and does not resubmit it

#### Scenario: Outcome remains uncertain
- **WHEN** reconciliation finds zero, multiple, inconsistent, stale, or unavailable matches
- **THEN** the account remains locked, new mutations remain blocked, and local operator resolution is required

### Requirement: Provider state precedes each mutation
Immediately before every mutation, the executor SHALL reconcile current orders, recent trades, positions, local outstanding intents, account identity, market freshness, clock state, rate budget, authorization state, and kills. Authentication, authorization, stale-data, clock, rate-limit, transport, or reconciliation failure SHALL block the mutation without simulator fallback or account switching.

#### Scenario: Position differs from local state
- **WHEN** provider position state cannot be reconciled with local orders and trades
- **THEN** the executor activates a reconciliation lock and sends no new mutation

### Requirement: Provider rate limits and failures are bounded
The local client SHALL enforce endpoint-specific request budgets below the documented Topstep Gateway limits, SHALL classify HTTP 429 separately, and SHALL apply a durable cooldown before further eligible requests. Generic retry middleware MUST NOT retry mutation endpoints.

#### Scenario: Provider returns HTTP 429
- **WHEN** a provider request is rate limited
- **THEN** the executor records a safe rate-limit outcome, activates the configured cooldown, and blocks new mutations until recovery is permitted

### Requirement: Cancellation and position close follow mutation safety
Order cancellation, modification, full close, and partial close SHALL use the same intent, attempt, acknowledgement, ambiguity, and reconciliation boundaries as order placement. A kill SHALL immediately prevent new entries, while cancel or flatten behavior SHALL require explicit local policy and provider confirmation.

#### Scenario: Kill activates while a position is open
- **WHEN** a local automatic or manual kill activates with an open position
- **THEN** new entries stop immediately and any configured cancel or close action is journaled and reconciled as a provider mutation

