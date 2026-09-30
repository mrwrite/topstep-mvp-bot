## ADDED Requirements

### Requirement: Secret protection
Broker credentials, refresh tokens, API keys, signing keys, and application secrets SHALL be encrypted with versioned envelope encryption backed by managed key custody, excluded from client responses, and redacted from logs, analytics, errors, traces, support data, and backups exports.

#### Scenario: Provider error echoes request headers
- **WHEN** an upstream error contains authorization or credential material
- **THEN** persisted and displayed diagnostics replace the material with a redaction marker and security tests detect no secret value

### Requirement: Security controls and dependency hygiene
External beta builds SHALL use pinned reproducible dependencies, protected CI, secret scanning, dependency and static analysis, secure headers, abuse controls, and remediation gates for exploitable high or critical findings.

#### Scenario: High-severity production advisory has a fix
- **WHEN** dependency scanning reports an applicable high-severity advisory with an available fix
- **THEN** the build is blocked from external beta until the fix or a documented time-bounded risk acceptance is approved and verified

### Requirement: Privacy lifecycle and backups
The system SHALL document collection purpose, retention, processors, geographic handling, export, deletion, legal holds, backup retention, restore access, and incident notification. Backup and restore procedures MUST be tested without exposing plaintext secrets.

#### Scenario: Restore drill completes
- **WHEN** operators restore a beta backup into an isolated environment
- **THEN** tenant isolation, key access, migration state, audit integrity, paper/live flags, and deletion tombstones are verified before the drill is accepted
