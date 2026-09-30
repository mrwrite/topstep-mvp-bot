## ADDED Requirements

### Requirement: Full live-readiness checklist
The frontend SHALL display a complete readiness checklist backed by backend gate state before enabling any live-related controls.

#### Scenario: Risk policy missing
- **WHEN** the backend reports `risk_policy_missing`
- **THEN** the dashboard shows the blocker and keeps trading controls disabled

### Requirement: Live acknowledgement flow
The frontend SHALL require users to review and accept scoped live-risk acknowledgements before any controlled live enablement can be requested.

#### Scenario: Acknowledgement expired
- **WHEN** the user's live acknowledgement is expired or invalidated
- **THEN** the UI blocks live controls and prompts for a new acknowledgement

### Requirement: Kill switch visibility and accessibility
The frontend SHALL keep kill switch state and stop controls visible, keyboard accessible, and clearly scoped to user/account/integration context.

#### Scenario: Mobile dashboard visible
- **WHEN** the dashboard is rendered on a mobile viewport
- **THEN** mode, readiness, kill switch, account, contract, and order status controls remain visible and non-overlapping

### Requirement: Risk and reconciliation status display
The frontend SHALL show risk lockout, account/equity freshness, order unknown state, and reconciliation-required status.

#### Scenario: Order enters timeout unknown
- **WHEN** an order is in `timeout_unknown`
- **THEN** the UI states that reconciliation is required and prevents repeat submission

### Requirement: Responsive and accessibility evidence
The project SHALL include automated or documented responsive and accessibility test evidence for auth, integrations, dashboard, readiness checklist, live acknowledgement, and emergency stop controls.

#### Scenario: Accessibility smoke test runs
- **WHEN** accessibility tests are run
- **THEN** critical trading controls have accessible names, keyboard focus, and no severe violations
