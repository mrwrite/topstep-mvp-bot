## ADDED Requirements

### Requirement: Explicit integration resolution
The system SHALL resolve broker, market-data, signal, account, and contract context from an authenticated user-scoped trading context before any trading action.

#### Scenario: Trading action uses selected integration
- **WHEN** an authenticated user starts a bot session or submits an order with a selected broker integration
- **THEN** the system uses only that user's selected integration and rejects the action if the integration is missing, inactive, credentialless, or incompatible

#### Scenario: Ambiguous integration is rejected
- **WHEN** multiple active broker integrations exist and no explicit default or request integration is available
- **THEN** the system rejects the trading action with a clear integration selection error

### Requirement: Truthful provider capability reporting
The system SHALL distinguish implemented provider capabilities from planned provider capabilities.

#### Scenario: Provider is configured but not implemented
- **WHEN** a provider adapter does not implement real order placement, contract lookup, account lookup, or market data
- **THEN** the API and UI mark that capability as unavailable and prevent live execution through that provider

### Requirement: Provider adapter conformance
Each enabled broker provider SHALL pass adapter conformance tests for authentication, account retrieval, contract lookup, order submission, order status retrieval, error normalization, and health diagnostics before it can be enabled for live trading.

#### Scenario: Provider lacks conformance coverage
- **WHEN** a provider is missing conformance tests for a claimed capability
- **THEN** that capability remains disabled for consumer trading

### Requirement: Contract fetching per selected integration
Tradable contracts SHALL be fetched from the selected market-data or broker integration and scoped to the selected account/environment.

#### Scenario: Live mode has no provider contracts
- **WHEN** live mode is selected and provider contract lookup fails
- **THEN** the system does not return fallback contracts as tradable options and displays a blocking error

#### Scenario: Paper mode uses demo contracts
- **WHEN** paper mode is selected and no provider contract feed is configured
- **THEN** the system may return demo contracts only if they are clearly labeled as simulated and cannot be submitted to a live broker

### Requirement: Provider-specific authentication state
The system SHALL model provider authentication/session states with provider-specific expiry, refresh, and failure details.

#### Scenario: Provider session expires
- **WHEN** a provider token expires during a bot session
- **THEN** the system refreshes the token if supported or pauses trading with a user-visible authentication error

### Requirement: Secure webhook signal integrations
Signal integrations SHALL require a stored secret or signed token and SHALL be bound to a user-owned broker routing configuration.

#### Scenario: TradingView webhook has no secret
- **WHEN** a webhook signal arrives for a signal integration without a configured secret
- **THEN** the system rejects the signal and records the rejected attempt

#### Scenario: Webhook routes to broker integration
- **WHEN** a valid webhook signal references a broker integration
- **THEN** the system verifies that the signal integration and broker integration belong to the same user before any order workflow begins
