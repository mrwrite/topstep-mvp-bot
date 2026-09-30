## ADDED Requirements

### Requirement: Truthful simulation evidence
The system SHALL distinguish simulated submissions, simulated fills, fees, slippage assumptions, stale data, and hypothetical performance from broker or actual-return evidence.

#### Scenario: Simulated fill display
- **WHEN** a simulation order receives a modeled fill
- **THEN** the UI SHALL label both order and fill simulated and itemize modeled costs and assumptions

### Requirement: Safe user controls
Start, pause, resume, stop, and kill commands SHALL be durable, idempotent, tenant-scoped, and visible with healthy, degraded, recovering, failed, or killed state.

#### Scenario: Repeated stop
- **WHEN** the same stop command is delivered repeatedly
- **THEN** the run SHALL reach one Stopped outcome without duplicate simulated orders

### Requirement: Recovery preserves risk checks
Restart recovery MUST re-run applicable risk, data freshness, kill, and reconciliation checks before continuing evaluation.

#### Scenario: Stale data after restart
- **WHEN** recovered market input exceeds the configured age
- **THEN** the run SHALL remain degraded or paused and SHALL not create a simulated order

### Requirement: Process-local execution prohibition
Beta-reachable simulation execution MUST NOT use process-local dictionaries, SSE request lifetime, Python locks, or UI state as ownership or recovery authority.

#### Scenario: Status stream reconnect
- **WHEN** a status client disconnects or reconnects
- **THEN** the durable run and worker ownership SHALL remain unchanged

### Requirement: Kill precedence across restart
Durable kill intent SHALL invalidate the current fence, cancel executable commands, survive application restart, and prevent recovery or takeover from returning the run to Running.

#### Scenario: Kill during takeover
- **WHEN** kill commits before a returning expired worker writes
- **THEN** the returning worker SHALL be rejected as stale and the run SHALL remain Killed

### Requirement: Checkpoint compatibility
Recovery MUST validate configuration hash and strategy version and MUST fail closed when the last durable checkpoint cannot be reconciled.

#### Scenario: Strategy version changed
- **WHEN** a checkpoint strategy version differs from the run snapshot
- **THEN** recovery SHALL enter Failed with a safe classification and SHALL emit no order

### Requirement: Deterministic RSI evaluation
`rsi-threshold-v1` SHALL run only in the fenced worker and identical canonical
lookback, strategy version, parameters, and checkpoint input SHALL produce the
same signal, rationale, and market snapshot.

#### Scenario: Deterministic replay
- **WHEN** the same versioned lookback and parameters are evaluated twice
- **THEN** both evaluation outcomes SHALL be identical

### Requirement: Reconciled simulation accounting
Recovery MUST reconcile evaluations, order intents, fills, positions, account
snapshots, ledger effects, modeled fees, P&L, daily risk state, and run risk
counters and MUST fail closed when committed records disagree.

#### Scenario: Position drift
- **WHEN** the persisted position differs from the checkpoint and reconciled fills
- **THEN** recovery SHALL enter Failed and SHALL NOT guess or silently repair quantity

#### Scenario: Duplicate economic delivery
- **WHEN** a committed evaluation is delivered again
- **THEN** order, fill, fee, ledger, position, and risk effects SHALL remain single

### Requirement: Transactional kill ordering
Kill and automated evaluation SHALL serialize on authoritative run state, kill
SHALL advance the fence and remain terminal, and no effect transaction ordered
after kill MAY commit.

#### Scenario: Kill at an evaluation boundary
- **WHEN** kill races with evaluation, order, fill, ledger, or checkpoint work
- **THEN** either the complete effect transaction commits before kill or it rolls back, and no partial or post-kill effect SHALL exist
