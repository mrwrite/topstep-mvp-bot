## ADDED Requirements

### Requirement: Deep order lifecycle states
The system SHALL support normalized order lifecycle states for created, risk-blocked, pending submission, submitted, accepted, rejected, partially filled, filled, cancel requested, canceled, expired, timeout unknown, reconciliation required, and failed orders.

#### Scenario: Provider returns partial fill
- **WHEN** a provider reports a partial fill
- **THEN** the order state becomes `partially_filled`, fill records are persisted, and remaining quantity remains trackable

### Requirement: Valid state transitions
The system SHALL enforce valid order state transitions and reject invalid transitions.

#### Scenario: Filled order receives accepted transition
- **WHEN** a terminal filled order receives a non-terminal accepted transition
- **THEN** the system rejects the transition and records an error event

### Requirement: Duplicate protection beyond idempotency
The system SHALL detect likely duplicate orders using normalized fingerprints and configurable time windows in addition to idempotency keys.

#### Scenario: Same bot signal repeats on same candle
- **WHEN** a bot emits the same side, symbol, account, contract, strategy, and candle timestamp within the duplicate window
- **THEN** the system suppresses the duplicate order and returns or records the existing order decision

### Requirement: Paper account ledger
Paper trading SHALL maintain durable ledger entries and account snapshots for balance, equity, margin assumptions, fills, fees, slippage, realized PnL, unrealized PnL, and manual adjustments.

#### Scenario: Paper order fills
- **WHEN** a paper order is filled
- **THEN** the system updates paper positions, fill records, ledger entries, realized/unrealized PnL where applicable, and account snapshot state

### Requirement: Safe retry and timeout handling
The system SHALL classify provider submission errors and SHALL reconcile unknown states before retrying any live order.

#### Scenario: Provider request times out after submission may have occurred
- **WHEN** a provider submit call times out in an unknown state
- **THEN** the order is marked `timeout_unknown`, live retry is blocked, and reconciliation is required before further action

### Requirement: Provider reconciliation
The system SHALL reconcile live orders, fills, open orders, and positions against provider state before presenting terminal order status or allowing new live orders after a mismatch.

#### Scenario: Provider position differs from app position
- **WHEN** provider position state differs from app-computed live position state
- **THEN** the account enters reconciliation-required status and new live orders are blocked until resolved
