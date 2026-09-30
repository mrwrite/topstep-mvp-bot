## ADDED Requirements

### Requirement: Hosted dry-run work is durable and isolated from order effects
Hosted Combine dry runs SHALL be tenant-scoped durable work claimed by a leased and fenced worker. They MUST bind the current integration/credential generation, exact approval version, restore epoch, risk-policy version, consent, strategy/configuration, and tenant-owned persisted market-input identity. A proposal SHALL be separately persisted as `dry_run_only` and MUST NOT be written to provider/paper order, fill, position, balance, fee, ledger, or realized-P&L tables.

#### Scenario: A worker retries a dry run
- **WHEN** a dry-run lease expires or a worker restarts before acknowledging completion
- **THEN** stable identity and fencing prevent duplicate proposals and stale commits

#### Scenario: Current Topstep read-only market/risk evidence is missing
- **WHEN** provider market data or reconciliation state cannot be verified
- **THEN** the dry run is degraded and cannot produce an eligible proposal or provider action

### Requirement: Provider state precedes recovery continuation
Recovery SHALL compare provider orders, trades/fills, positions, and timestamps with local intent, acknowledgement, ledger, checkpoint, and kill state before continuation.

#### Scenario: State is inconsistent
- **WHEN** provider and local state cannot be reconciled authoritatively
- **THEN** the run remains degraded, no new order is sent, and an operator-visible safe failure is recorded

### Requirement: Authentication and rate failure stops safely
Authentication, authorization, session, rate-limit, stale-data, or reconciliation failure SHALL stop new provider submissions and apply the configured cooldown without automatic account switching or simulator fallback.

#### Scenario: Provider rate limit occurs
- **WHEN** the provider rejects a request due to rate limiting
- **THEN** durable state records the safe outcome and new submissions remain blocked until policy permits recovery
