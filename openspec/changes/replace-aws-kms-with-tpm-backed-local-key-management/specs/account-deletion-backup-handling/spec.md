## ADDED Requirements

### Requirement: Recovery-aware backup lifecycle
Backup restore and account deletion SHALL preserve key dependency, tombstone, recovery-wrap, and audit evidence until restored credentials are either verifiably rewrapped or cryptographically erased.

#### Scenario: Backup restored to replacement Pi
- **WHEN** a protected backup is restored to a replacement device
- **THEN** credential use SHALL remain blocked until recovery rewrapping and tombstone reconciliation complete
