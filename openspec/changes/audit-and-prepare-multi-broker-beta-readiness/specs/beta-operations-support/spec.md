## ADDED Requirements

### Requirement: Staged release gates
The system SHALL support internal verification, invite-only simulation, invite-only broker-paper, limited live, and broader-release stages with objective entry and exit criteria. Failure of any critical security, authorization, execution, reconciliation, risk, data-loss, or secret-management gate MUST independently produce no-go.

#### Scenario: Average score passes but critical gate fails
- **WHEN** readiness scoring meets the numeric target but order idempotency or tenant isolation is unverified
- **THEN** the release decision remains no-go and identifies the critical blocker

### Requirement: Controlled cohorts and support
Each beta stage SHALL define enabled providers/environments, maximum users/accounts, support owner and hours, severity targets, observability, required documents, retention, known-risk acceptances, incident thresholds, and rollback triggers.

#### Scenario: Cohort exceeds approved size
- **WHEN** admitting an invite would exceed the stage's user or account cap
- **THEN** admission is blocked until an authorized stage change is recorded

### Requirement: Incident containment and rollback
Operators SHALL be able to stop new bot runs, activate server-side account or global kill switches, disable a provider, pause workers, preserve evidence, notify affected users, roll back a compatible build, restore data, and reconcile before reopening.

#### Scenario: Duplicate-order incident is detected
- **WHEN** monitoring detects or suspects duplicate live or paper orders
- **THEN** affected execution is paused immediately, accounts are reconciled, rollback criteria are evaluated, users are notified according to severity, and reopening requires documented approval

### Requirement: Honest product and legal communication
Product materials SHALL identify supported and unsupported platforms, paper/live status, simulation limitations, fees and modeled costs, pricing, data use, support boundaries, and trading risks without profit guarantees. Legal and regulatory conclusions MUST be reviewed by qualified counsel.

#### Scenario: Platform is roadmap-only
- **WHEN** a user views or attempts to configure a roadmap provider
- **THEN** the product labels it unavailable, states the missing technical or contractual prerequisites, and does not collect credentials
