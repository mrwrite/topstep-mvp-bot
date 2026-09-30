## 1. P0 Simulation-Beta Blockers: Hardware-Backed Secrets

- [ ] 1.1 Complete provider-neutral schema-2 envelope, audit, rotation, recovery, and PostgreSQL migration evidence; cryptography/context/tamper tests pass but durable audit and PostgreSQL evidence remain open.
- [x] 1.2 Add development/test-only local provider and physical-TPM production validation; verify production rejects local, cloud, missing, recovery-private, and invalid configuration.
- [ ] 1.3 Complete controlled Fernet inventory/dry-run/migration/verification/envelope-only cutover and offline rollback retention; do not close until production inventory is zero and legacy reads are rejected.
- [ ] 1.4 DEFERRED FOR HOSTED COMBINE ONLY: provision and drill the owner-approved physical TPM architecture, rotation, restored-backup replacement-Pi recovery, reboot/failure/lockout, and non-exportability evidence for the self-hosted/future-live profile.

## 2. P0 Simulation-Beta Blockers: Universal Tenant Isolation

- [x] 2.1 Inventory every tenant-owned route, model query, service, job, report, export, reconciliation, simulation, operator, and fixture path in traceability.
- [x] 2.2 Introduce tenant-required repositories and verified job tenant envelopes; verify missing, forged, stale, and cross-tenant contexts fail closed.
- [x] 2.3 Migrate all beta-reachable direct tenant ORM access to the mandatory boundary without weakening risk, reconciliation, launch, or live-rejection gates.
- [x] 2.4 Add architectural/static enforcement and negative tests for reads, writes, credentials, sessions, reports, analytics, export, deletion, jobs, and bot controls.

## 3. P0 Simulation-Beta Blockers: Durable Runs and Recovery

- [x] 3.1 Add one linear migration for simulation runs, leases, commands, checkpoints, outbox events/deliveries, audit outcomes, and deletion tombstones.
- [x] 3.2 Implement the persisted state machine and compare-and-set transition service with invalid/stale transition tests.
- [x] 3.3 Implement lease acquire/renew/expire/takeover with monotonically increasing fencing and stale-owner tests.
- [x] 3.4 Implement tenant-scoped idempotent commands and concurrent start/pause/resume/stop/kill tests.
- [x] 3.5 Implement transactional outbox creation, claim, idempotent consumption, bounded retry, and terminal failure handling.
- [x] 3.6 Implement checkpoints and restart recovery that rechecks kill, reconciliation, risk, and data freshness before evaluation.
- [x] 3.7 Pass crash-before/after-commit, publication crash, duplicate delivery, lease loss, takeover, restart, database interruption, kill-during-recovery, and duplicate-worker tests with no duplicate simulated order.

## 4. P0 Simulation-Beta Blockers: Operator Outcomes

- [ ] 4.1 Add correlated append-only authorization, start, success, failure, partial, and cancellation audit services with safe summaries.
- [ ] 4.2 Wrap every beta operator read/mutation and verify target binding, authorized success/failure, denial, partial revocation, and redaction.
- [ ] 4.3 Add an architectural test preventing ordinary update/delete access to operator audit events.

## 5. P0 Simulation-Beta Blockers: Deletion, Backup, and Restore

- [ ] 5.1 Implement authenticated deletion cancellation, holds/retention exceptions, tombstones, purge state, and auditable receipts.
- [ ] 5.2 Implement backup manifest/export and tombstone reapplication so restore cannot resurrect identities, sessions, or credentials.
- [x] 5.3 Add a repeatable isolated deletion/backup/restore drill producing JSON and Markdown evidence and pass it.
- [ ] 5.4 Complete an owner-managed backup purge/restore game day; keep open until timestamped infrastructure evidence exists.

## 6. P0 Simulation-Beta Blockers: Quality and Reproducibility

- [ ] 6.1 Produce a warning inventory by category/source/owner/risk and fix application-owned actionable warnings.
- [ ] 6.2 Commit a narrow warning budget and CI check that rejects new/unapproved warnings without broad suppression.
- [ ] 6.3 Install production and development Python locks in an empty environment and pass pip check, import, migrations, full tests, and demo smoke.
- [ ] 6.4 Remove frontend dependencies, run clean npm ci, and pass tests, build, and production audit.
- [ ] 6.5 Run Python dependency audit, disposition every finding, and fail CI for unaccepted production findings.

## 7. P0 Simulation-Beta Blockers: Operations and Release Evidence

- [ ] 7.1 Add release-evidence manifest generation with command, status, duration, revision, environment, counts, and hashes.
- [ ] 7.2 Expand CI for focused security, tenant, recovery/failure injection, warning budget, clean locks, migration, drill, frontend, audit, demo, OpenSpec, secret scan, and artifact retention.
- [x] 7.3 Document exact protected-branch rules and required checks; keep host-passed status open until repository-host evidence exists.
- [ ] 7.4 Implement configurable cohort cap, invitation/revocation, suspension, maintenance, health/degraded state, rollback triggers, abuse controls, and feedback intake.
- [ ] 7.5 Obtain owner approval for cohort size, support owner/hours/escalation, retention, incident thresholds, legal documents, and beta risk acceptance.

## 8. P1 Beta-Critical Improvements: Simulation Honesty and UX

- [ ] 8.1 Audit and test the complete registration-to-support simulation journey at API and runtime UI levels.
- [ ] 8.2 Add persistent simulation-only, hypothetical-performance, stale-data, degraded-state, and modeled-cost indicators.
- [ ] 8.3 Display durable run states and safe start/pause/resume/stop/kill/recovery controls with accessibility and responsive tests.
- [ ] 8.4 Itemize modeled spread, fees, slippage, and fill assumptions without presenting them as brokerage execution.

## 9. Owner-Controlled Release Gates

- [ ] 9.1 Confirm physical TPM inventory, persistent handles, authorization delivery, offline recovery objectives/custodian, deployment topology, and retirement authority.
- [ ] 9.2 Confirm protected branch settings and one green protected revision with retained evidence.
- [ ] 9.3 Confirm staffed support, legal/privacy/retention approvals, incident exercise, cohort cap, and suspension authority.
- [ ] 9.4 Issue a signed simulation-beta go/no-go decision in which any critical blocker vetoes release.

## 10. Paper-Account Beta Prerequisites

- [x] 10.1 Keep broker paper-account beta NO-GO until a separate approved adapter, delegated auth, capability conformance, sandbox lifecycle, market-data, reconciliation, and commercial review change passes.

## 11. Live-Money Prerequisites

- [x] 11.1 Preserve backend live rejection and keep live-money beta NO-GO until a separate approved live-safety, legal, provider, operations, and controlled rollout change passes.

## 12. Hosted Topstep Trading Combine Child

- [ ] 12.1 Complete `deploy-invite-only-topstep-combine-beta-to-vercel-and-railway`, including hosted key management, exact-account approval, dry run, deployment, deletion, backup/restore, and controlled acceptance evidence. Risk-policy/schema and dry-run scaffolding plus post-fix software regression are recorded; provider-backed dry-run readiness, route-level policy/consent tests, deployment, full PostgreSQL race matrix, backup-platform restore, and controlled acceptance remain open.
- [ ] 12.2 Obtain owner approval for tester identity, origins, Railway environment, account policy, risk policy, secrets, backup, rollback, and incident procedures.
- [x] 12.3 Keep Express Funded and Live Funded/live-brokerage stages NO-GO and preserve server-side live rejection.

## 13. Post-Beta Improvements

- [ ] 13.1 Evaluate external queue/read-model scaling only after measured simulation-beta load and incident evidence; cloud key services remain prohibited.
- [ ] 13.2 Reduce all actionable warnings to zero and remove expired temporary allowances.
