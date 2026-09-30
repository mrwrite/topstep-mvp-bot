## ADDED Requirements

### Requirement: Scoped hosted provider exception
The system SHALL permit only `railway-secret-envelope-v1` as the environment-backed root-key provider and only for the explicit one-user hosted Combine mode; arbitrary environment/file master keys remain prohibited in production.

#### Scenario: Generic environment provider configured
- **WHEN** production configuration selects an unnamed, development, file, or generic environment key provider
- **THEN** startup fails closed

### Requirement: TPM deferral is profile-specific
Physical TPM evidence SHALL remain incomplete and required for the planned self-hosted profile and future live/live-credential readiness, but SHALL NOT block only the explicitly scoped Railway-hosted Combine gate.

#### Scenario: Hosted gate is assessed
- **WHEN** reviewers assess the one-user Combine beta
- **THEN** they apply the hosted provider requirements without marking or claiming physical TPM tasks complete
