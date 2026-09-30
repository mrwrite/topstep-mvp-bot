## ADDED Requirements

### Requirement: Hardware key-management veto
Invite-only simulation beta SHALL remain NO-GO until physical TPM provisioning, non-exportability, restart/reboot, rotation, database restore, replacement-Pi recovery, Fernet cutover, warnings, clean installation, backup, operational approval, cohort policy, and protected-host CI evidence pass.

#### Scenario: Unit tests pass without hardware evidence
- **WHEN** provider-neutral and mocked TPM tests pass but any physical or operational evidence is absent
- **THEN** internal testing MAY remain GO while invite-only simulation beta remains NO-GO
