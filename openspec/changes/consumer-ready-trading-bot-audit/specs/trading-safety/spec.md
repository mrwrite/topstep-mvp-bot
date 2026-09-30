## ADDED Requirements

### Requirement: Central pre-trade risk checks
Every order intent SHALL pass a centralized risk engine before broker or paper execution.

#### Scenario: Risk check fails
- **WHEN** an order intent violates any configured risk rule
- **THEN** the system rejects the order before provider submission and records the risk decision

### Requirement: Max daily loss enforcement
The system SHALL enforce user/account daily loss limits using realized PnL, available provider equity data, and app-owned order/fill records.

#### Scenario: Daily loss limit reached
- **WHEN** the daily loss limit is reached or cannot be reliably calculated in live mode
- **THEN** the system locks live trading for that account until the configured reset condition

### Requirement: Position and size limits
The system SHALL enforce max trade size, max contracts, and max open position limits before placing an order.

#### Scenario: Order exceeds max contracts
- **WHEN** an order quantity would exceed the user's max contract limit for the selected account or symbol
- **THEN** the system rejects the order and explains the violated limit

### Requirement: Account balance and equity checks
The system SHALL verify account balance, equity, buying power, or provider-equivalent account state before live execution when the selected provider supports account data.

#### Scenario: Account data unavailable
- **WHEN** live trading is requested and required account data cannot be retrieved
- **THEN** the system blocks live execution instead of submitting the order

### Requirement: Duplicate order prevention
The system SHALL prevent duplicate orders caused by webhook retries, UI repeat submissions, bot loop repetition, or network retries.

#### Scenario: Duplicate idempotency key
- **WHEN** an order intent arrives with an idempotency key that was already accepted
- **THEN** the system returns the existing order result and does not submit a second provider order

### Requirement: Confirmation and live-mode acknowledgement
The system SHALL require explicit user acknowledgement before live trading and SHALL require confirmation for manual orders unless the user has enabled a scoped automation rule.

#### Scenario: User has not acknowledged live trading risk
- **WHEN** a user attempts to enable live trading without a current risk acknowledgement
- **THEN** the system blocks live trading and presents the required acknowledgement flow

### Requirement: User-scoped kill switch
The system SHALL provide an authenticated, user-scoped kill switch that stops automation and, where supported, cancels open orders or flattens positions.

#### Scenario: Kill switch is activated
- **WHEN** a user activates the kill switch for an account
- **THEN** the system stops that user's bot sessions, blocks new orders for the account, records the event, and invokes supported provider cancel/flatten actions

### Requirement: Paper and live separation
The system SHALL separate paper trading state, credentials, orders, fills, positions, and risk limits from live trading state.

#### Scenario: Paper order is placed
- **WHEN** a paper order is placed
- **THEN** the system records it in paper trading records and never submits it to a live broker adapter
