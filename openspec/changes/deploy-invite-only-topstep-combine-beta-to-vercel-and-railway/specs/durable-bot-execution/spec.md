> **Superseded execution target (2026-10-02):** Railway command ownership applies to internal simulation and read-only work only. `add-local-topstep-combine-executor` governs Topstep provider mutations on the personal device.

## ADDED Requirements

### Requirement: Provider execution remains command-owned
Trading Combine work SHALL be represented by durable database commands and executed only by a worker holding the current lease and fencing token; request and streaming processes MUST NOT execute provider orders.

#### Scenario: Duplicate worker attempts execution
- **WHEN** two workers observe the same command
- **THEN** only the current fenced claimant may progress provider submission and stale claimants fail closed

### Requirement: Deployment-safe handoff
Worker shutdown and restart SHALL stop new claims, preserve or expire leases predictably, checkpoint progress, and require provider reconciliation before a replacement worker continues.

#### Scenario: Deployment interrupts reconciliation
- **WHEN** a worker stops after provider submission but before local acknowledgement
- **THEN** the successor reconciles provider state before deciding whether any new submission is safe

### Requirement: Credential work carries generation and epoch
Every Topstep credential-dependent run, command, job, and outbox event SHALL carry tenant, integration, credential generation, security epoch, stable identity, correlation, and causation evidence, and consumers SHALL revalidate those bindings before side effects.

#### Scenario: Stale work is replayed after deletion or restore
- **WHEN** a worker claims work bound to a deleted generation or older security epoch
- **THEN** it terminally suppresses or safely cancels the work without provider authentication or infinite retry
