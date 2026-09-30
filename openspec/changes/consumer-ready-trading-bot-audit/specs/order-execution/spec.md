## ADDED Requirements

### Requirement: Normalized order intent
The system SHALL represent every trade request as a normalized order intent containing user, account, provider, contract, side, quantity, order type, time-in-force, mode, strategy source, and idempotency key.

#### Scenario: Missing order field
- **WHEN** a required order intent field is missing or invalid
- **THEN** the system rejects the order before risk evaluation or provider submission

### Requirement: Supported order types
The system SHALL support market, limit, stop, and stop-limit order intents only when the selected provider supports the requested type.

#### Scenario: Unsupported order type
- **WHEN** a user requests an order type unsupported by the selected provider
- **THEN** the system rejects the order with a provider capability error

### Requirement: Durable order lifecycle
The system SHALL persist order, order event, fill, and position lifecycle data for every paper and live order.

#### Scenario: Provider accepts order
- **WHEN** a provider returns an accepted provider order id
- **THEN** the system stores the provider order id, normalized status, request payload metadata, and audit event

### Requirement: Fill confirmation and status tracking
The system SHALL confirm order status and fills through provider polling, provider callbacks, or reconciliation jobs before presenting an order as filled.

#### Scenario: Provider response is non-terminal
- **WHEN** provider submission returns a non-terminal accepted or pending status
- **THEN** the system continues tracking the order until filled, canceled, rejected, expired, or unknown

### Requirement: Failed and unknown order handling
The system SHALL classify failed execution attempts as rejected, retryable, or unknown and SHALL reconcile unknown states before retrying.

#### Scenario: Network timeout after submission
- **WHEN** provider submission times out after the request may have reached the provider
- **THEN** the system marks the order unknown, queries provider state using idempotency or client order id, and does not blindly resubmit

### Requirement: Execution audit trail
The system SHALL audit every trade action, including request creation, risk decisions, provider submission, provider responses, status changes, fills, cancellations, user confirmations, and errors.

#### Scenario: Order rejected by risk engine
- **WHEN** the risk engine rejects an order
- **THEN** the system records the rejected order intent and risk reason in the audit trail

### Requirement: Position reconciliation
The system SHALL reconcile app-owned position state with provider position state for live accounts.

#### Scenario: Position mismatch detected
- **WHEN** provider position state differs from app-computed position state
- **THEN** the system flags the account as requiring reconciliation and blocks new live orders until resolved
