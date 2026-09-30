## ADDED Requirements

### Requirement: Consumer-ready trading dashboard
The dashboard SHALL present trading mode, selected provider, selected account, selected contract, risk status, bot status, and latest order status before allowing trading actions.

#### Scenario: Dashboard is missing readiness prerequisite
- **WHEN** a required prerequisite such as account, contract, risk policy, or provider health is missing
- **THEN** the dashboard disables trading actions and displays the blocking prerequisite

### Requirement: Integration selection UX
The integration UI SHALL show provider implementation status, supported capabilities, credential status, environment, account availability, and health diagnostics.

#### Scenario: Provider is roadmap only
- **WHEN** a user selects a provider whose trading adapter is not implemented
- **THEN** the UI labels it as unavailable for live trading and prevents activation for execution

### Requirement: Contract and account selection UX
Users SHALL explicitly select a validated account and contract for the selected provider before starting a live or paper trading session.

#### Scenario: Account not selected
- **WHEN** a user attempts to start a session without selecting an account
- **THEN** the UI blocks the session start and asks the user to select an account

### Requirement: Trading mode clarity
The UI SHALL make paper, demo, signal-only, and live automation modes visually and textually distinct.

#### Scenario: User enables auto trade
- **WHEN** a user toggles automation on
- **THEN** the UI displays whether automation is paper or live and requires live-risk acknowledgement before live automation

### Requirement: Clear user-facing states
The UI SHALL provide actionable loading, error, empty, unavailable, and success states for authentication, integrations, contracts, accounts, bot sessions, analysis, backtests, and orders.

#### Scenario: Contract provider fails
- **WHEN** provider contract loading fails
- **THEN** the UI explains that provider contracts are unavailable and does not silently present fallback contracts as live-tradable

### Requirement: Provider-neutral terminology
The product UI SHALL use generic broker/trading terminology except where a provider-specific name is required.

#### Scenario: Non-TopStepX provider is selected
- **WHEN** a user selects Tradovate, NinjaTrader, IBKR, ETX, or TradingView
- **THEN** the dashboard and setup flow do not refer to the app as TopStepX-specific

### Requirement: Demo and investor readiness
The app SHALL provide a safe investor/demo package that demonstrates workflows using paper trading or mocked providers without exposing live credentials or placing live orders.

#### Scenario: Demo mode is active
- **WHEN** demo mode is active
- **THEN** all execution, account, and contract data is labeled simulated or demo and cannot route to live providers

### Requirement: Mobile and accessibility readiness
Critical trading setup, monitoring, and stop controls SHALL remain usable at common desktop, tablet, and mobile breakpoints.

#### Scenario: Mobile viewport opens dashboard
- **WHEN** the dashboard is rendered on a mobile viewport
- **THEN** the mode, stop control, account, contract, and order status remain visible and non-overlapping
