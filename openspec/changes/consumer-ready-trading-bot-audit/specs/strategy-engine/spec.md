## ADDED Requirements

### Requirement: Versioned strategy configuration
The system SHALL persist versioned strategy configurations per user, account, trading mode, and symbol scope.

#### Scenario: Bot session starts
- **WHEN** a bot session starts
- **THEN** the system records the exact strategy version and parameters used by that session

### Requirement: Explicit strategy behavior
The system SHALL accurately name and describe implemented strategy logic without implying unsupported indicators or predictive accuracy.

#### Scenario: RSI threshold strategy is selected
- **WHEN** the current RSI threshold strategy is selected
- **THEN** the UI and API describe it as RSI-threshold based and do not claim moving-average or momentum confirmation unless implemented

### Requirement: Strategy data quality gate
The system SHALL block strategy evaluation when market data is stale, incomplete, insufficient, or missing required indicator values.

#### Scenario: Latest bar is stale
- **WHEN** the latest market data bar is older than the allowed staleness threshold
- **THEN** the strategy emits no trade signal and records a data-quality warning

### Requirement: Paper trading simulation
The system SHALL provide a paper execution path with simulated orders, fills, positions, equity, and PnL before live automation is enabled.

#### Scenario: Strategy emits paper signal
- **WHEN** a strategy emits a signal in paper mode
- **THEN** the paper execution engine simulates order lifecycle and updates paper position/equity state

### Requirement: Backtesting assumptions and metrics
The system SHALL report backtesting assumptions and metrics including fees, slippage, tick value, drawdown, win/loss, exposure, and trade count when sufficient data exists.

#### Scenario: Backtest completes
- **WHEN** a backtest completes
- **THEN** the response includes metrics and a clear list of simulation assumptions

### Requirement: Strategy guardrails
The system SHALL support strategy guardrails such as cooldowns, max signals per period, no-trade windows, and risk-policy binding.

#### Scenario: Strategy cooldown active
- **WHEN** a strategy emits a signal during an active cooldown window
- **THEN** the system suppresses the trade and records the guardrail decision
