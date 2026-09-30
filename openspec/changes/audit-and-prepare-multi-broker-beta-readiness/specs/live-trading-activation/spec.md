## ADDED Requirements

### Requirement: Live trading is default-deny
Live order execution SHALL remain disabled until a separately reviewed release enables it and all security, provider, legal, risk, reconciliation, operational, and user gates pass. A feature flag or entitlement alone MUST NOT enable live submission.

#### Scenario: Fully entitled beta user requests live order
- **WHEN** a beta user with valid paper access and entitlements submits a live intent before live release approval
- **THEN** the server rejects it before adapter submission and records the blocking gates

### Requirement: Explicit activation ceremony
Any future live activation SHALL require provider-verified live account identity, unmistakable live indicators, reauthentication, typed or equivalent account confirmation, versioned informed consent, a completed safety checklist, recent paper evidence, and a short-lived server-side grant.

#### Scenario: User omits one confirmation
- **WHEN** any activation confirmation or current readiness evidence is missing
- **THEN** no live grant is issued and the response identifies every unmet gate

### Requirement: Activation revocation and drift
The server SHALL revoke live grants on user request, credential or account change, policy/version change, risk-policy change, reconciliation lock, incident, provider restriction, or expired readiness evidence.

#### Scenario: Provider capability changes
- **WHEN** a provider no longer permits the configured automation or account environment
- **THEN** the grant is revoked, runs stop before new submissions, and users/operators are notified
