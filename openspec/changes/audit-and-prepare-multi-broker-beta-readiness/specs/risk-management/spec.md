## ADDED Requirements

### Requirement: Server-side pre-trade risk
Every order intent SHALL pass a transactional server-side risk evaluation immediately before submission using current positions, pending exposure, balances, data freshness, connectivity, session state, reconciliation locks, and configured limits.

#### Scenario: Concurrent intents exceed exposure
- **WHEN** two workers concurrently evaluate orders whose combined reserved exposure exceeds a limit
- **THEN** at most the allowed exposure is reserved and submitted, and the other intent is rejected with an audited reason

### Requirement: Required risk limits
The risk policy SHALL support daily loss, order quantity/notional, position, symbol and portfolio exposure, open-position count, trade count, consecutive-loss, session, and account-level limits. Unknown required inputs MUST block new entries.

#### Scenario: Daily loss limit is reached
- **WHEN** realized plus policy-defined unrealized loss reaches the configured daily limit
- **THEN** the account is locked against new entries until the versioned reset policy is satisfied

### Requirement: Emergency controls
The kill switch SHALL be durable, server-enforced, account-scoped, immediately block new submissions, and expose separate capability-aware actions for canceling orders and flattening positions. Client availability MUST NOT be required.

#### Scenario: Kill switch is activated during worker outage
- **WHEN** the server records an active kill switch while a worker is disconnected
- **THEN** every worker observes it before its next submission, new orders remain blocked after restart, and activation latency is measurable
