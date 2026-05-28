## ADDED Requirements

### Requirement: Centralized trading context resolution
The system SHALL resolve every trading-sensitive operation through a centralized `TradingContextService`.

#### Scenario: Route requests trading context
- **WHEN** a manual, scheduler, webhook, strategy, contract, account, or order route receives a trading-sensitive request
- **THEN** the route obtains a trading context from `TradingContextService` before risk evaluation or execution

#### Scenario: Context cannot be resolved
- **WHEN** user, mode, integration, account, contract, provider health, or required capability cannot be resolved
- **THEN** the system rejects the operation with structured readiness blockers and does not place an order

### Requirement: User ownership enforcement
The trading context SHALL enforce user ownership for every referenced integration, account, contract selection, order, strategy config, bot session, position, and audit event.

#### Scenario: Cross-user resource referenced
- **WHEN** a user references another user's trading resource
- **THEN** the system rejects the request without exposing the other resource's details

### Requirement: Provider capability and health binding
The trading context SHALL bind provider capability metadata and provider health diagnostics to each trading-sensitive decision.

#### Scenario: Provider lacks capability
- **WHEN** a selected provider does not implement a required capability for the requested action
- **THEN** the system blocks the action and reports the missing capability

### Requirement: Readiness blocker response model
The trading context SHALL return stable readiness blocker codes for frontend and launch gate evaluation.

#### Scenario: Account is missing
- **WHEN** an account is required and no valid selected account exists
- **THEN** the response includes a blocker code such as `missing_account`
