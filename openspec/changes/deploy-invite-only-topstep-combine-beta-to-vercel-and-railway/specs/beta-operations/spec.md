## ADDED Requirements

### Requirement: Hosted operations and rollback
Operators SHALL maintain runbooks for service deployment, migrations, readiness, worker handoff, origin policy, secret rotation, backup restoration, provider incidents, kills, tester offboarding, and rollback with exact target and approval controls.

#### Scenario: Rollback is invoked
- **WHEN** hosted acceptance fails or a credential incident occurs
- **THEN** provider execution is disabled, kills and revocations are applied, in-flight state is reconciled, and compatible data is preserved for recovery

### Requirement: Redacted operational evidence
Logs, traces, analytics, audits, health responses, commands, and acceptance artifacts MUST NOT contain Topstep usernames, API keys, session tokens, root keys, account IDs, or personal information.

#### Scenario: Provider raises a secret-bearing error
- **WHEN** an upstream exception includes request or authentication material
- **THEN** structured logging and client responses emit only a redacted classification and correlation identifier

### Requirement: Human-controlled provider order
The first minimum-size Trading Combine order SHALL require immediate explicit operator confirmation after connectivity, dry-run, risk, approval, and kill evidence passes.

#### Scenario: CI executes acceptance checks
- **WHEN** automated CI reaches the real-order acceptance step
- **THEN** the step is skipped and no provider order is sent

### Requirement: Restore reconciliation is revoke-by-default
The hosted restore runbook SHALL require execution and worker processing disabled, a higher external security epoch, redacted operator evidence, revocation of every restored Topstep integration, and fresh tester onboarding and approval.

#### Scenario: Reconciliation fails partway
- **WHEN** restored-work suppression or epoch advancement fails
- **THEN** credential-dependent processing remains fail-closed and the same correlation-bound ceremony can resume without contacting Topstep
