## ADDED Requirements

### Requirement: Five independent release stages
Release governance SHALL independently assess internal software testing, invite-only internal simulation, one-user Topstep Trading Combine beta, Express Funded beta, and Live Funded/live-brokerage beta.

#### Scenario: Initial hosted assessment
- **WHEN** regressions and existing internal gates pass but hosted acceptance is incomplete
- **THEN** internal stages may be GO, the Combine stage remains conditional or NO-GO, and both funded stages remain NO-GO

### Requirement: Combine consequences and consent
The system SHALL disclose that provider execution is simulated but can affect evaluation status, account rules, and subscription value, and SHALL require explicit tester consent before automated provider execution.

#### Scenario: Consent absent
- **WHEN** the tester has not accepted the current disclosure
- **THEN** provider order enablement is denied

### Requirement: Evidence is stage-specific
Software mocks MUST NOT close Vercel, Railway, provider sandbox, real order, deletion/revocation, TPM, or live-stage gates.

#### Scenario: Unit tests pass without deployment credentials
- **WHEN** all local tests pass but external evidence is unavailable
- **THEN** external acceptance tasks remain incomplete
