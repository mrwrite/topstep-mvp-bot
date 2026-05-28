## ADDED Requirements

### Requirement: Persisted risk settings
The system SHALL persist risk settings per user, account, integration, and trading mode before any live trading can be enabled.

#### Scenario: Live mode without risk policy
- **WHEN** live trading is requested without an active persisted risk policy
- **THEN** the system blocks live trading before order creation

### Requirement: Daily risk state and lockouts
The system SHALL persist daily risk state and enforce daily loss, equity, and risk lockout rules.

#### Scenario: Daily loss limit reached
- **WHEN** realized PnL, equity drawdown, or provider account data shows the daily loss limit is reached
- **THEN** the system activates a lockout and blocks new orders for the scoped account

### Requirement: Account and equity snapshots
The system SHALL use fresh account/equity snapshots for live risk decisions and SHALL fail closed when required account data is stale or unavailable.

#### Scenario: Provider account state unavailable
- **WHEN** live mode requires account equity and the selected provider cannot return current account state
- **THEN** the risk engine blocks live order creation

### Requirement: Persisted kill switch
The system SHALL provide persisted user/account/integration scoped kill switch records that block orders and automation in scope.

#### Scenario: Kill switch active
- **WHEN** a kill switch is active for a user, account, integration, or bot session
- **THEN** new orders and bot starts in that scope are blocked and the event is audited

### Requirement: Risk decision audit
The system SHALL record every risk decision with the evaluated policy, inputs, result, blocker reason, and related order/context identifiers.

#### Scenario: Risk check rejects order
- **WHEN** a risk rule rejects an order
- **THEN** the system persists the decision and exposes the scoped reason to the user
