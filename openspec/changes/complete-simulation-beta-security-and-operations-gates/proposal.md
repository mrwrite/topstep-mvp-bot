## Why

The bot is safe enough for internal paper-only verification but still lacks the managed-secret, universal isolation, durable execution, deletion/restore, reproducibility, quality, and operational evidence required for external users. This change closes application-owned simulation-beta blockers while preserving the server-side prohibition on broker-paper and live execution.

## What Changes

- Introduce a provider-neutral envelope-encryption service with authenticated context binding, versioned keys, rotation, fail-closed production configuration, and development-only local keys.
- Make tenant context mandatory for beta-reachable resources, jobs, reports, execution, reconciliation, export, deletion, and operator investigation.
- Replace process-local simulation ownership with persisted runs, fenced leases, checkpoints, idempotent commands, a transactional outbox, recovery, and terminal failure handling.
- Extend purpose-bound operator audit evidence from authorization decisions through safe post-action outcomes.
- Complete deletion cancellation, retention/legal-hold behavior, backup purge/restore protection, and repeatable deletion drills.
- Remediate application-owned warnings and enforce a narrow warning budget.
- Verify backend and frontend installation from committed locks in clean environments.
- Define protected release checks and retain machine-readable verification evidence without claiming host-level branch protection.
- Add minimum simulation-beta cohort, support, incident, health, suspension, and rollback controls where owner policy is not required.
- Make simulation-only environment, hypothetical results, simulated order/fill state, costs, stale data, and degraded operation unmistakable.
- Preserve all paper/demo behavior, risk gates, reconciliation locks, kill switches, and live-trading rejection.

## Capabilities

### New Capabilities

- `managed-secret-protection`: Envelope encryption, key-provider restrictions, rotation, context binding, audit, and outage behavior.
- `tenant-isolation`: Mandatory server-derived tenant context across synchronous, background, reporting, and operator paths.
- `durable-bot-execution`: Persisted simulation runs, leases, fencing, commands, checkpoints, outbox, recovery, and kill behavior.
- `operator-auditing`: Purpose-bound authorization plus append-only action-start and outcome evidence.
- `account-deletion-backup-handling`: Grace, cancellation, holds, erasure, retention, backup purge/restore protection, and drills.
- `dependency-reproducibility`: Clean locked installs and undeclared-dependency detection.
- `quality-warning-control`: Warning classification, remediation, budgets, and CI enforcement.
- `simulation-onboarding`: Invite-only simulation setup and unambiguous environment/risk communication.
- `simulation-execution-recovery`: Observable simulated order/fill behavior, recovery, duplicate suppression, and safe controls.
- `beta-operations`: Cohort, eligibility, support, incidents, health, degraded behavior, maintenance, abuse, feedback, and suspension.
- `release-governance`: Protected-check definitions, evidence retention, critical vetoes, and truthful stage decisions.

### Modified Capabilities

None. The prior readiness change remains unarchived, so these requirements are expressed as new delta capabilities and trace back to its authoritative gaps.

## Impact

Affected areas include authentication and authorization dependencies, credential encryption and migrations, bot scheduling/execution, risk and kill-switch integration, database models and Alembic, audit and account lifecycle services, operational endpoints and documentation, frontend simulation controls and status language, backend/frontend dependency workflows, CI, tests, and OpenSpec evidence. No brokerage adapter or real-money execution capability is added.
