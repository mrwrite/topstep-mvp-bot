## ADDED Requirements

### Requirement: Critical-veto release gate
Release evaluation SHALL independently veto simulation beta for any unresolved critical secret, tenant, durability, duplicate-execution, kill-recovery, deletion/restore, reproducibility, warning, operational, or CI blocker.

#### Scenario: High average with critical blocker
- **WHEN** aggregate readiness is high but one critical gate lacks evidence
- **THEN** simulation beta SHALL remain NO-GO

### Requirement: Retained verification evidence
Required checks SHALL emit retained evidence containing command, exit status, duration, revision, environment, test/warning counts, and artifact hashes.

#### Scenario: Missing host evidence
- **WHEN** repository-host branch protection or a green protected run cannot be verified
- **THEN** that owner-controlled gate SHALL remain open and SHALL not be described as passed

### Requirement: Stage separation
Broker paper-account and live-money stages MUST remain NO-GO and inaccessible under this change.

#### Scenario: Live request
- **WHEN** any user requests live execution
- **THEN** the backend SHALL reject it regardless of simulation readiness

### Requirement: Durable execution evidence
The release evidence SHALL include the durable failure-injection suite and direct PostgreSQL concurrency tests for same-key and same-scope starts.

#### Scenario: SQLite-only concurrency evidence
- **WHEN** concurrency tests have run only on SQLite
- **THEN** the durable execution gate SHALL remain open

#### Scenario: Session-only restart evidence
- **WHEN** recovery has been tested only with new ORM sessions in one process
- **THEN** the restart gate SHALL remain open until a terminated worker process is replaced against the same PostgreSQL database

### Requirement: Universal tenant evidence
The protected release checks SHALL run syntax-aware request-boundary checks, the
complete negative tenant matrix, signed-job substitution tests, and direct
PostgreSQL tenant-relationship tests.

#### Scenario: Route bypass introduced
- **WHEN** a mounted beta request module adds a direct tenant ORM query outside the reviewed allowlist
- **THEN** the architectural check SHALL fail the release gate

#### Scenario: Repository-host evidence absent
- **WHEN** the repository CI definition includes tenant checks but no protected-host run is available
- **THEN** host CI SHALL remain an open owner gate even if local checks pass

### Requirement: Physical key-management evidence veto
The self-hosted production profile and any future live/live-credential release SHALL be vetoed until physical TPM provisioning/non-exportability/restart/reboot/failure/rotation evidence, restored-backup replacement-Pi recovery, zero active Fernet records, envelope-only rejection, runtime legacy-key removal, and key-custody/retirement approval are retained. Those physical artifacts SHALL NOT veto only the explicitly scoped one-user Railway-hosted Trading Combine stage when every hosted-key and hosted-acceptance requirement passes.

#### Scenario: Software verification only
- **WHEN** unit, integration, or emulated-provider tests pass but a physical or operational key-management artifact is absent
- **THEN** internal testing MAY proceed, hosted Combine readiness is decided by its independent hosted gates, and self-hosted/live profiles remain NO-GO

### Requirement: Five-stage release assessment
Governance SHALL independently assess internal software testing, invite-only internal simulation, one-user Topstep Trading Combine beta, Express Funded beta, and Live Funded/live-brokerage beta.

#### Scenario: Hosted child incomplete
- **WHEN** internal regression gates pass but any hosted child task or external acceptance artifact is incomplete
- **THEN** the first two stages MAY be GO, the Trading Combine stage SHALL remain NO-GO, and both funded/live stages SHALL remain NO-GO
