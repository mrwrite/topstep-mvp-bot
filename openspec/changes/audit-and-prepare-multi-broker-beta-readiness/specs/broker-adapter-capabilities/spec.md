## ADDED Requirements

### Requirement: Canonical adapter contract
Each broker adapter SHALL implement or explicitly reject authentication and refresh, account discovery, instrument metadata, market-data subscription, historical bars, quotes, positions, balances, order preview, submit, cancel, replace, order/fill/rejection events, reconciliation snapshots, and health checks.

#### Scenario: Adapter omits required operation
- **WHEN** conformance tests call an operation the provider does not support
- **THEN** the adapter returns a typed unsupported-capability result and does not simulate success or fall back to another provider

### Requirement: Versioned capability discovery
Each adapter SHALL expose a versioned capability manifest describing supported environments, assets, data entitlements, order types, lifecycle events, rate limits, session behavior, geographic restrictions, and commercial approval state.

#### Scenario: Configuration exceeds provider capability
- **WHEN** preflight requests an unsupported order type, instrument, environment, or data channel
- **THEN** activation is rejected before trading with the exact capability and provider restriction

### Requirement: Provider throttling and normalization
Adapters SHALL obey provider rate limits, normalize errors without losing provider identifiers, and expose retryability separately from reconciliation requirements.

#### Scenario: Provider returns rate limit
- **WHEN** a provider returns a rate-limit response
- **THEN** the adapter updates its rate budget, delays safe reads, blocks unsafe automatic order retries, and exposes a degraded health state
