## ADDED Requirements

### Requirement: TPM operating procedures
Operations SHALL maintain approved provisioning, inventory, rotation, migration, backup/restore, replacement recovery, lost-device, TPM failure, lockout, recovery compromise, and retirement procedures.

#### Scenario: Destructive key action
- **WHEN** a persistent TPM key or recovery/legacy artifact would be evicted or destroyed
- **THEN** operations SHALL require exact target identity, dependency inventory, successful backup and recovery evidence, explicit approval, and rollback implications
