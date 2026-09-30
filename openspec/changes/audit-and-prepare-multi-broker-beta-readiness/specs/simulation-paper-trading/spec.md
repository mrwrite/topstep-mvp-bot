## ADDED Requirements

### Requirement: Explicit simulation environment
Simulation and broker-paper runs SHALL remain visibly and durably separate from live trading. The system MUST NOT silently promote a configuration, connection, order, or result from paper to live.

#### Scenario: Paper run is started
- **WHEN** a user starts an eligible simulation or broker-paper configuration
- **THEN** the API, UI, audit events, orders, metrics, and notifications identify the exact paper environment and no live credential is used

### Requirement: Truthful execution model
Local simulation SHALL document and report fill, spread, slippage, fee, margin, liquidity, session, corporate-action, and contract-expiry assumptions. Performance reports MUST include applicable costs and MUST state that simulated results do not predict future returns.

#### Scenario: Simulation report is generated
- **WHEN** a user views or exports performance
- **THEN** realized and unrealized P&L, fees, modeled slippage, data period, strategy version, assumptions, and limitations are included

### Requirement: Reproducible backtests
Backtests SHALL record an immutable configuration, code version, data identity, time range, timezone, cost models, random seed if used, and data-quality warnings. They MUST prevent look-ahead and disclose unresolved survivorship-bias limitations.

#### Scenario: Backtest is rerun
- **WHEN** the same versioned inputs and source data are available
- **THEN** the system produces the same orders and metrics or reports the exact non-reproducible dependency
