## ADDED Requirements

### Requirement: Paper beta launch checklist
The system SHALL expose a paper-beta launch checklist separate from live-readiness gates.

#### Scenario: Checklist evaluated
- **WHEN** the beta launch checklist is evaluated
- **THEN** it reports pass/fail for account lifecycle, legal acceptance, invite gate, onboarding, support, monitoring, analytics, entitlements, migrations, paper trading safety, documentation, and live-disabled status

### Requirement: Launch gates block beta invitation waves
The project SHALL require P0 paper-beta gates to pass before sending new invite waves.

#### Scenario: P0 launch gate fails
- **WHEN** a P0 beta launch gate fails
- **THEN** admin invite-wave actions are blocked or require documented override in non-production environments only

### Requirement: Operational readiness
The project SHALL document operational readiness for paper beta support.

#### Scenario: Support incident occurs
- **WHEN** a beta support incident occurs
- **THEN** the runbook explains how to inspect user status, onboarding state, legal acceptance, invite status, paper orders, risk blockers, and diagnostics while keeping live trading disabled

### Requirement: Support readiness
The beta SHALL have support ownership, contact paths, response expectations, and escalation criteria.

#### Scenario: Support readiness reviewed
- **WHEN** launch readiness is reviewed
- **THEN** the checklist shows support contact, owner, escalation, severity labels, and known response expectations

### Requirement: Documentation readiness
The beta SHALL have user-facing and operator-facing documentation before launch.

#### Scenario: Documentation gate evaluated
- **WHEN** beta launch gates are evaluated
- **THEN** missing onboarding, FAQ, disclosure, support, deployment, or runbook docs fail the documentation gate

### Requirement: Beta success metrics
The project SHALL define success metrics for invite-only beta.

#### Scenario: Beta metrics reviewed
- **WHEN** beta launch is reviewed
- **THEN** success metrics include activation, completion of first paper session, support volume, blocker frequency, retention, paper engagement, and safety incident count

### Requirement: Live remains blocked during beta
The beta launch checklist SHALL require live trading unavailable status.

#### Scenario: Live trading appears enabled
- **WHEN** health, launch gate, entitlement, or UI state indicates live trading is available
- **THEN** paper beta launch readiness fails
