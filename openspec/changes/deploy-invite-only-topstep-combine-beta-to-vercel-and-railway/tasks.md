> **Superseded execution target (2026-10-02):** Tasks that would give Railway custody of Topstep credentials or provider mutation authority are historical and MUST NOT be implemented. `add-local-topstep-combine-executor` owns replacement work; hosted read-only, migration, deletion, and telemetry controls remain applicable.

## 1. Release and Trust Reconciliation

- [x] 1.1 Update the parent release model, design, readiness, traceability, tasks, and affected specifications for the five independent stages and Trading Combine consequences.
- [x] 1.2 Reconcile the TPM child so all physical tasks remain incomplete but are explicitly deferred and non-blocking only for the one-user Railway Combine beta.
- [x] 1.3 Document the hosted trust model, Railway envelope-key risk acceptance, residual risks, and stage-specific go/no-go criteria.

## 2. Hosted Envelope Provider

- [x] 2.1 Implement the explicit `railway-secret-envelope-v1` provider with 256-bit versioned keys, AES-256-GCM wrapping, canonical context, typed failures, health, cleanup, and no implicit fallback.
- [x] 2.2 Enforce the hosted deployment profile, active/prior key configuration, separation from other application secrets, startup failure rules, and safe status reporting.
- [x] 2.3 Integrate hosted-provider rotation with idempotent DEK-only rewrapping and missing-prior-key failure behavior.
- [x] 2.4 Add architecture checks prohibiting arbitrary production environment/file keys, secret exposure, AWS, and hosted-provider use outside its approved profile.
- [x] 2.5 Add deterministic hosted-provider configuration, uniqueness, context-substitution, tampering, restart, rotation, and redaction tests.

## 3. Credential Onboarding and Session Safety

- [x] 3.1 Add durable tenant-owned credential, account-discovery, session-expiry, and onboarding-state schema with a linear migration.
- [x] 3.2 Implement backend-only Topstep login-key authentication and active-account search returning only safe metadata.
- [x] 3.3 Encrypt credentials immediately, safely manage expiring session tokens, roll back failed onboarding, and emit redacted audit outcomes.
- [x] 3.4 Implement credential replacement, revocation, and dedicated-key guidance without returning or repopulating secrets.
- [x] 3.5 Add onboarding success/failure, session refresh/expiry, response/log redaction, and cross-tenant negative tests.

## 4. Account Attestation and Administrative Approval

- [x] 4.1 Persist server-derived account ownership snapshots, Combine attestation, and exact tenant/user/integration/account approvals with expiry, approver, purpose, label, and correlation ID.
- [x] 4.2 Enforce one approved account, no name-based classification, indistinguishable cross-tenant failures, and mandatory reapproval after account or credential changes.
- [x] 4.3 Add administrator approval, emergency revocation, and revoke-and-kill APIs with audit outcomes.
- [x] 4.4 Add ownership, override, attestation, approval, expiry, revocation, switching, and tenant-isolation tests.

## 5. Trading Combine Execution and Risk Boundary

- [ ] 5.1 Complete a simulated-only Topstep adapter using official endpoints and explicit `live: false` for contract/market selection; leave undocumented provider behavior fail-closed.
- [ ] 5.2 Require durable worker identities and revalidate credential, ownership, approval, dry run, risk, freshness, reconciliation, fencing, and kills before each provider submission.
- [ ] 5.3 Separate provider intent, attempt, acknowledgement, order, fill/trade, position, and ledger facts and reconcile ambiguous outcomes before any retry.
- [ ] 5.4 Enforce the one-tester server-owned risk policy, explicit allowlists, quantity one, schedule/cooldowns, and global/tenant/account/run kills.
- [ ] 5.5 Implement read-only provider dry run, explicit consequence consent, and a gate that prevents order enablement until both are current.
- [ ] 5.6 Add simulated-only, risk, idempotency, ambiguity, provider-failure, rate-limit, restart, fencing, deployment-handoff, and kill tests.

## 6. Vercel and Railway Deployment Surface

- [ ] 6.1 Add Vercel configuration, strict headers/CSP, public-variable allowlist, exact-origin API configuration, and bundle/response secret checks.
- [ ] 6.2 Add masked onboarding, account selection, attestation, approval-pending, health, consent, dry-run, kill, disconnect, and deletion interfaces that clear sensitive state.
- [ ] 6.3 Add separate Railway API and worker start commands, health/readiness/heartbeat, graceful lease handoff, migration release step, and non-authoritative Redis integration.
- [x] 6.4 Add placeholder-only Vercel/Railway secret inventory, deployment, backup/restore, rollback, and origin/trusted-proxy/cookie/rate-limit runbooks.
- [ ] 6.5 Add frontend onboarding, preview-origin rejection, secret scan, clean install, test, build, and production audit evidence.

## 7. Disconnect, Deletion, and Incidents

- [x] 7.1 Implement an authoritative credential tombstone that revokes sessions/approval, kills runs, cancels pending commands, and suppresses recovery/outbox reuse before ciphertext deletion.
- [ ] 7.2 Implement administrator emergency revocation, API-key replacement, provider-auth failure, suspected compromise, root-key rotation, and tester-offboarding workflows.
- [x] 7.3 Document restored-backup revocation reconciliation, audit retention without secrets, and tester Topstep key-revocation confirmation.
- [ ] 7.4 Add active-run deletion, deletion-race, outbox-redelivery, restored-backup, and revocation tests using PostgreSQL where concurrency matters.

## 8. Software Verification and OpenSpec

- [x] 8.1 Run focused hosted-provider, onboarding, approval, adapter, risk, deletion, tenant, durable, recovery, and architecture tests and record exact evidence.
- [x] 8.2 Run PostgreSQL migration/concurrency/fencing/recovery/deletion tests and verify one linear Alembic head from an empty database.
- [x] 8.3 Run the full backend, warning count, pip check/audit if available, compileall, frontend clean install/tests/build/audit, demo smoke, and git diff checks.
- [x] 8.4 Strictly validate the parent, deferred TPM child, and hosted-beta child and correct every validation error.
- [x] 8.5 Create a redacted evidence report distinguishing mocks, local services, external deployments, provider sandbox, and human-confirmed order evidence.

## 9. External Deployment and Controlled Acceptance

- [ ] 9.1 Deploy and verify Railway PostgreSQL, Redis, controlled migration, API with provider execution disabled, and separate worker with provider execution disabled.
- [ ] 9.2 Deploy and verify the Vercel frontend, exact production/preview CORS, HTTPS authentication, secure headers, and absence of secrets in bundles and responses.
- [ ] 9.3 Onboard the invited tester, verify encrypted credentials and account ownership, collect Combine attestation, and grant time-bounded approval for the exact redacted account ID.
- [ ] 9.4 Complete read-only connectivity, dry run, kill, API restart, worker restart/fencing, backup/restore, disconnect/deletion, and Topstep key-revocation acceptance evidence.
- [ ] 9.5 Only after immediate explicit owner authorization, submit and reconcile one minimum-size Trading Combine order; record redacted authorization and provider identifiers, or leave this task open.

## 10. Final Approval

- [ ] 10.1 Obtain owner approval for tester identity, exact origins, Railway environment, cohort/account policy, instruments, strategy, schedule, numeric risk limits, secret custodians, backups, rollback, and incident procedures.
- [ ] 10.2 Reassess every release stage independently; Express Funded and Live Funded/live-brokerage stages MUST remain NO-GO in this change.

## 11. Durable Session and Restore-Safety Continuation

- [x] 11.1 Implement database-authoritative session renewal with generation binding, provider validation, fenced single-flight lease, takeover, and expired-lease rejection.
- [x] 11.2 Enforce replacement, revocation, deletion, and epoch mismatch precedence; bind credential-dependent runs, commands, and outbox work to database-derived generation and epoch values.
- [x] 11.3 Implement monotonic `HOSTED_SECURITY_EPOCH`, fail-closed startup/readiness, and operator-controlled revoke-by-default restore reconciliation.
- [ ] 11.4 Complete and rerun the real PostgreSQL race/failure matrix, including renewal takeover, deletion, recovery, stale work, and restored backup cases.
- [x] 11.5 Add deterministic renewal, reauthentication, lease/fence, epoch, restore-suppression, and failure-injection tests; record that these are local software tests only.
- [x] 11.6 Run fresh SQLite migration to the single Alembic head and retain exact local verification evidence.

## 12. Hosted Risk, Consent, and Dry-Run Readiness

- [x] 12.1 Add tenant/integration/account/cohort-bound versioned hosted risk-policy, consent, dry-run, and dry-run-only proposal records with a linear Alembic migration.
- [ ] 12.2 Add explicit versioned Combine consent acceptance and purpose-bound operator policy creation; missing, incomplete, expired, mismatched, empty-allowlist, or relaxed-over-one-quantity policy fails closed. Core service code exists, but endpoint-level persistence, authorization, mismatch, and expiry tests are still needed.
- [ ] 12.3 Complete durable dry-run readiness and worker processing against authoritative read-only Topstep market/reconciliation evidence; retain fencing, repeat eligibility checks, and prove no order/ledger side effects.
- [x] 12.4 Remove the Topstep broker-trading capability claim, add explicit startup mutation-disabled checks, and reject order/cancel/modify/close adapter methods.
- [x] 12.5 Add Vercel frontend-only security/build configuration, Railway API/worker topology template, separate worker entrypoint, and placeholder-only deployment/rollback guide.
- [ ] 12.6 Complete production preflight, including real secret separation, current database policy validation, exact deployed origins, and post-build secret scan; retain all real deployment checks open.
- [ ] 12.7 Complete consent/risk-policy/durable progress/proposal UX and verify Vercel preview-origin rejection; no execution/enable-trading control is permitted.
- [ ] 12.8 Add PostgreSQL policy-update/worker-lease/cancellation races and the remaining individual lifecycle race cases; do not close 7.4 or 11.4 on partial evidence.
- [x] 12.9 Complete full post-fix backend/frontend/dependency/warning/migration/demo regression; deployment preflight remains intentionally failing without owner-approved production configuration, and external deployment/provider evidence remains open.
