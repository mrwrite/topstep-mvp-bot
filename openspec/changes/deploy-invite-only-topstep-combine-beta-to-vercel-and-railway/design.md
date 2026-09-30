## Context

The application already has tenant-scoped durable commands, fenced workers, checkpoints, outbox delivery, deterministic evaluation, risk and ledger workflows, server-side live-trading rejection, and provider-neutral record envelopes. The previous production target was a self-hosted Raspberry Pi with a physical TPM. The immediate owner-approved target is instead one invited tester using one administratively approved Topstep Trading Combine through a Vercel frontend and separate Railway API, worker, PostgreSQL, and Redis services.

A Trading Combine is simulated provider execution, but provider actions can change evaluation status, account-rule compliance, and the value of the tester's subscription. It therefore receives a stronger authorization and acceptance boundary than the internal simulator. Express Funded, Live Funded, live brokerage, and multi-user rollout are excluded.

## Goals / Non-Goals

**Goals:**

- Deploy a reversible one-user hosted beta without AWS or browser/Vercel custody of Topstep secrets.
- Encrypt user-owned Topstep credentials before PostgreSQL persistence using a versioned hosted-beta envelope provider.
- Prove selected-account ownership, require Combine attestation, and require approval for the exact tenant/user/integration/account tuple.
- Keep all authoritative execution in the durable Railway worker with fencing, approval revalidation, conservative risk controls, kill switches, and provider reconciliation.
- Provide safe onboarding, dry run, disconnect, deletion, incident response, rollback, and evidence capture.
- Defer rather than complete or delete physical TPM requirements.

**Non-Goals:**

- Express Funded Accounts, Live Funded Accounts, live brokerage, live-money trading, or a live-provider adapter.
- Multi-user or multi-account availability, automatic account classification, or name-pattern authorization.
- Claiming Railway variables provide TPM-equivalent protection.
- Browser-, HTTP-, SSE-, WebSocket-, Vercel-, or API-process-owned trading execution.
- Automated real-provider order submission in CI.

## Decisions

### Five-stage release model

Release stages are internal software testing, invite-only internal simulation, one-user Trading Combine beta, Express Funded beta, and Live Funded/live-brokerage beta. Only the first two can inherit existing GO evidence. The Combine stage is conditional on every child gate. Both funded stages remain NO-GO. This prevents simulated provider execution with real evaluation consequences from being mislabeled as ordinary internal simulation.

### Hosted topology and authority

Vercel serves only static/frontend code and holds only the public Railway API URL. Railway exposes the FastAPI service publicly and runs a separate non-public durable worker. PostgreSQL is authoritative for commands, approvals, leases, checkpoints, outbox, risk, and deletion state. Redis is limited to rate limiting, short-lived coordination/cache, and health; it is never authoritative. API restarts cannot own or interrupt execution. The worker claims commands using existing leases and fencing and relinquishes them gracefully on shutdown.

### Explicit Railway hosted-beta envelope provider

`railway-secret-envelope-v1` is an explicit provider accepted only when the deployment profile is `hosted_topstep_combine_beta`. Each configured key version maps to an independently generated 32-byte secret supplied through Railway service variables. The provider wraps each record DEK with AES-256-GCM using a fresh nonce and canonical AAD binding provider, environment, tenant, integration, credential record, envelope schema, and wrapping-key version. New writes use only the active version; approved prior versions are unwrap-only during rotation. No generic environment-key fallback exists.

The provider does not store root keys in PostgreSQL, Redis, images, source, logs, Vercel, or browser responses. Startup rejects missing, malformed, duplicate, unknown, or production-incompatible versions. Railway project administrators and a compromised authorized runtime can access the configured secret; the owner accepts that limitation only for this single Trading Combine beta. TPM remains the planned self-hosted profile.

### Credential and session flow

An authenticated user submits TopstepX platform username and API key over HTTPS to FastAPI. The API calls `POST /api/Auth/loginKey`, validates the success flag/error code/token, then calls `POST /api/Account/search` with `onlyActiveAccounts: true`. It returns only safe account metadata. The API key is encrypted immediately with context for the owning tenant/integration/credential record; plaintext is never returned or logged. Failed onboarding is rolled back.

Provider session tokens are durably persisted because the Railway worker must survive API and worker restarts without process-local authority. Each token is separately enveloped with tenant/integration/generation context and an explicit expiry. It is never reused after expiry, credential replacement, approval revocation, disconnect, deletion, or provider-identity change. Refresh will reauthenticate from the encrypted user-owned key through the same service boundary; until that refresh path is implemented, expiry fails closed. Replacement invalidates account approval and stops active runs.

### Account ownership, attestation, and approval

Account search proves only that an ID was returned for the credential; it does not prove account type. The system persists a server-derived discovery snapshot. Selection requires a snapshot match, tester Combine attestation, and an administrator approval for the exact tenant, user, integration, provider account ID, safe label, purpose, expiry, approver, and correlation ID. The initial cohort permits one active approval. Account changes and credential replacement require a new approval. Names are display-only.

Emergency revocation atomically expires approval, activates account/tenant/run kill controls, cancels pending commands, and prevents new provider submissions. Cross-tenant and nonexistent resources use indistinguishable authorization failures where appropriate.

### Durable Trading Combine execution boundary

Provider execution requires tenant ID, user ID, integration ID, approved account ID, run ID, command ID, and fencing token. The worker revalidates credential state, discovery ownership, unexpired approval, attestation, dry-run evidence, risk policy, data freshness, reconciliation state, and kills before run start and immediately before each provider submission. Contract lookup and market selection always pass `live: false`.

Order intent, provider submission attempt, acknowledgement, provider order, fill/trade, position, and local ledger reconciliation remain separate durable facts. Stable custom/provider tags are used only where official support is established. A timeout after submission is ambiguous: the worker reconciles provider state before any retry and never silently resubmits. Provider failure never falls back to the internal simulator, switches accounts, or fabricates a fill.

### Initial risk policy and consent

Server-owned policy limits the cohort to one tester, tenant, integration, and approved account; quantity to one contract; and instruments/strategies to explicit allowlists. It also enforces open-position, orders/session, orders/day, daily-loss, consecutive-loss, stale-data, schedule, and provider-error cooldown limits plus global, tenant, account, and run kills. Browser input can only request stricter limits. Read-only dry run performs auth, account lookup, simulated contracts/market data, signals, and proposed-order evaluation without submission. Separate explicit tester consent and successful dry-run evidence are prerequisites for enabling provider orders.

### Deletion and revocation

Disconnect establishes a durable credential tombstone before ciphertext deletion, expires sessions, revokes approval, kills runs, cancels pending commands, and causes worker/recovery/outbox paths to fail closed. Audit records retain identifiers and outcomes but never credential material. The tester is instructed to revoke the dedicated key in TopstepX. Backups may retain encrypted historical ciphertext only under documented retention; restored data remains unusable because tombstones and revocations are authoritative.

### Hosted risk policy, consent, and dry-run boundary

`HostedCombineRiskPolicy` is a tenant/integration/account/cohort-bound, versioned operator record.
Its JSON contract requires explicit nonempty strategy/version and instrument allowlists, all order,
position, loss, freshness, schedule and cooldown limits, dry-run enabled, and provider-order execution
disabled. Quantity is fixed at one for this cohort. No financial threshold or instrument is populated
as a production default; an operator must set and approve them. Each new policy version requires
fresh tester consent and stale dry-run records fail their policy-version checks.

`HostedCombineConsent` retains the exact accepted text/version and binds the current credential
generation, account approval, policy version, tester, and correlation ID. This is affirmative product
consent, not a waiver of security obligations.

`HostedCombineDryRun` is an idempotent queue record owned by the durable worker using a DB lease and
fencing token. It rechecks approval, credential generation, restore epoch, policy, consent, run, and
persisted market-input identity before evaluation. Proposals live in a separate `HostedCombineProposal`
table with a database constraint fixing status to `dry_run_only`; provider order tables and ledger
paths are not called. A deleted/replaced integration invalidates queued work through current-state
revalidation. Missing authoritative Topstep read-only market/risk/reconciliation evidence is currently
classified degraded, not replaced with internal paper values and not represented as successful
provider readiness. Therefore this implementation slice does not yet produce a release-qualifying
Topstep dry run.

### Read-only provider capabilities and deployment artifacts

Topstep capability declarations omit broker trading. The adapter mutation methods reject before
network I/O, and hosted startup rejects a mutation-enabled configuration. Existing authenticated
account onboarding remains separate from dry-run market/reconciliation evidence; no real provider
calls are added here.

Vercel config lives under `frontend/` and serves only the static build. Its CSP intentionally contains
an invalid API-host placeholder to replace with the exact approved Railway hostname. Railway templates
share an image but require per-service command configuration: API has `SERVICE_ROLE=api`, while a
private worker runs `python -m app.worker_entrypoint` with `SERVICE_ROLE=worker`. Production rejects
the development combined role. A deployment preflight validates secret names and database policy
binding without printing values; it cannot substitute for deployed CORS, build, provider, backup, or
recovery evidence.

### Vercel and Railway controls

The frontend compiles only explicitly public configuration. API CORS accepts the exact production origin and explicitly approved previews, never a wildcard. Credential fields are masked, non-repopulating, telemetry-excluded where practical, and cleared after submission. CSP and secure headers are deployment-owned.

Railway uses service-specific start commands, API liveness/readiness, worker heartbeat, controlled Alembic migration, graceful lease handoff, secure cookies, trusted-proxy validation, rate limits, structured redaction, and PostgreSQL backup/restore instructions. No persistent volume is authoritative. Secret inventory uses placeholders and never includes the tester's API key as a deployment variable.

### TPM reconciliation

The TPM implementation and evidence remain intact at 17/26 completed tasks. Physical provisioning, non-exportability, replacement-Pi recovery, production Fernet migration, and related approvals stay unchecked and are labeled deferred. They do not block only the explicit hosted Combine stage; they continue to block the self-hosted production profile and any future live/live-credential readiness unless the owner makes another explicit decision.

## Risks / Trade-offs

- **Railway administrators or a compromised runtime can access the envelope root key** → Limit scope to one tester/Combine, separate the key from all other secrets, rotate, audit access, support deletion, and prohibit funded/live use.
- **Topstep account search does not classify a Combine** → Require ownership snapshot, tester attestation, exact administrator approval, and prohibit name-based inference.
- **Provider submission outcome can be ambiguous** → Persist intent/attempt and reconcile provider orders/trades before retry; fail closed if official behavior is unclear.
- **A deployment can interrupt a worker** → Use separate services, fencing, heartbeats, graceful shutdown, expired-lease recovery, and reconciliation before continuation.
- **Encrypted credentials can survive in backups** → Tombstones/revocation remain authoritative after restore; document retention and root-key rotation/revocation consequences.
- **One successful software test can be overread as deployment evidence** → Keep Vercel, Railway, provider sandbox, dry-run, and human-confirmed order tasks open until real evidence exists.
- **Preview deployments can broaden origin access** → Use an explicit preview allowlist and keep production Railway APIs inaccessible to arbitrary previews.

## Migration Plan

1. Add schema and software controls with provider execution disabled.
2. Generate hosted envelope key material offline and enter it directly in Railway without command output; deploy PostgreSQL/Redis, migrate, then deploy API and worker separately.
3. Deploy Vercel frontend with exact Railway URL and origin allowlist; verify bundle and response secret scans.
4. Invite one tester, onboard credentials, discover ownership, collect attestation, and grant time-bounded exact-account approval.
5. Run connectivity, dry run, kill, API restart, worker restart/fencing, deletion, and restore drills.
6. Only with immediate explicit operator authorization, submit one minimum-size Combine order and reconcile it. This step is never CI automation.
7. Roll back by disabling provider execution, activating kills, revoking approval, draining/canceling commands, reconciling in-flight state, reverting application services, and preserving the compatible database until evidence approves schema rollback.

## Open Questions

- Which exact Vercel production and preview origins, Railway project/environment, tester identity, instruments, strategy, schedule, and numeric loss/order limits will the owner approve?
- Which Topstep custom-tag/idempotency and order/trade reconciliation behaviors are confirmed by current official documentation or sandbox evidence?
- What measured provider limits and validation behavior should control the future encrypted-session refresh interval?
- What Railway PostgreSQL backup/point-in-time recovery tier and restoration objective will be purchased and tested?
- Will the owner authorize the single minimum-size provider order after dry-run and kill evidence passes?

## Durable onboarding slice decision record

### Inventory and reuse

| Existing artifact | Decision |
| --- | --- |
| `PlatformIntegration` and tenant repository | Retained as tenant-owned integration identity and mandatory access boundary |
| Provider-neutral envelope encryption | Retained; extended with purpose-specific protected-value contexts |
| Topstep login and active-account projection | Retained behind the onboarding service; tokens and raw responses never enter API output or audit metadata |
| Adapter token cache | Retained only as a per-call optimization; encrypted database session state is authoritative |
| Metadata `approvedAccountId` and first-account selection | Removed as authorization paths |
| Generic physical integration deletion | Rejected for Topstep; the durable deletion workflow is mandatory |
| Legacy direct Topstep order helpers | Disabled; this slice cannot submit provider orders |
| Simulation runs, commands, outbox, kills, and recovery | Retained and terminally suppressed for matching integration work during replacement/disconnect/deletion |

### Data classification

| Data | Storage | Classification / rule |
| --- | --- | --- |
| Username, API key, session token | Separate versioned envelopes in PostgreSQL | Secret; never returned, logged, audited, or stored in frontend/Vercel |
| API-key fingerprint | HMAC-SHA256 with a dedicated service secret | Pseudonymous duplicate signal; never a plain hash |
| Account ID and display label | Tenant snapshot rows | Restricted safe selection metadata; never account-type authority |
| Attestation and approval | Tenant rows with exact generation/account references | Authorization evidence, not secret material |
| Lifecycle audit | `SecurityAuditEvent` | Identifiers, generation, counts, reason classification only |
| Tombstone | Tenant/integration/generation plus keyed identity hash | Terminal authorization evidence without credential ciphertext |

### Integration and approval state machines

Integration transitions are compare-and-set/row-lock protected:
`pending_validation -> validated -> account_discovered -> awaiting_attestation -> awaiting_approval -> approved`.
Replacement enters `replacing` and returns only to `awaiting_attestation`; revocation enters
`revoking -> revoked`; deletion enters `deleting -> deleted`. `suspended` and `failed` are
non-executable. `deleted` is terminal. No revoked approval becomes approved without a new
explicit purpose-bound operator action.

Approval is `approved -> expired|revoked`. The active partial unique index permits at most one
unrevoked approved account for a tenant/integration. Approval binds tenant, integration,
credential generation, provider, exact account, discovery row, attestation, tester, cohort,
operator, purpose, case, correlation, and expiry.

### Execution eligibility decision table

| Required fact | Missing/stale result |
| --- | --- |
| active integration and current encrypted credential | deny `credential_unavailable` or `integration_not_approved` |
| encrypted unexpired session for current generation | deny `provider_session_unavailable` |
| current unexpired discovery and attestation | deny discovery/attestation classification |
| exact current unrevoked approval | deny `approval_not_current` |
| active tester membership and configured single-tester cohort | deny cohort/membership classification |
| all applicable kill switches clear | deny `kill_switch_active` |
| server live flag remains false | deny `live_trading_configuration_forbidden` |

This function is the sole future entry point for dry-run/provider eligibility. It does not submit
orders in this slice.

### Disconnect/deletion transaction and race policy

Replacement validates new credentials before locking or mutating the old generation. On commit it
revokes sessions, snapshots, attestations, and approvals, kills matching active runs, cancels their
pending commands, and terminally suppresses matching outbox work. Disconnect performs the same
authorization suppression while preserving encrypted credentials for an explicit reconnect policy.
Deletion additionally erases credential and token envelopes, writes a keyed tombstone, reduces
integration metadata to non-secret deletion evidence, and enters terminal `deleted`. Retries return
success without resurrection.

The database prevents cross-tenant parent references and multiple current credential generations or
active approvals. Row locks serialize service transitions; PostgreSQL partial unique indexes decide
concurrent insert races. Stale session refresh, approval, worker, recovery, command, or outbox work
must re-read the tombstone/lifecycle/eligibility state and fail closed.

## Durable session renewal and restore-safety decision record

### Session authority and state machine

The encrypted `TopstepProviderSession` row is authoritative; the adapter's process cache is only a
request optimization and can never establish eligibility. Session states are `valid`, `renewing`,
`expired`, `failed`, `revoked`, and `deleted` (absence represents `absent`). Each row binds tenant,
integration, credential generation, security epoch, session generation, expiry,
renewal-not-before time, lease owner/expiry, monotonic fencing token, attempt count, safe failure
classification, and lifecycle version. Renewal advances the session generation and replaces prior
ciphertext in one fenced compare-and-set commit.

### Validation and reauthentication decision table

| Condition | Decision |
| --- | --- |
| token is outside the renewal window | use the committed encrypted session; no provider call |
| renewal due and no live lease | claim a higher fence, call `/api/Auth/validate`, require `success`, zero error code, and `newToken` |
| another live lease exists | fail `renewal_in_progress`; never make a competing provider call |
| lease expires | a new owner may take over with a higher fence; the old owner cannot commit |
| provider explicitly rejects the session and policy permits | decrypt only the current generation inside the provider boundary and reauthenticate |
| timeout, outage, rate limit, malformed, or ambiguous response | classify safely and fail closed |
| lifecycle, generation, or epoch changes | reject the result; replacement, revocation, deletion, and restore reconciliation win |

### External security epoch and restore reconciliation

`HOSTED_SECURITY_EPOCH` is a non-secret positive monotonic deployment value. The database stores
its last reconciled epoch separately. A lower environment value is rejected; a higher value makes
old integrations, sessions, approvals, commands, runs, and outbox work non-executable. Startup keeps
recovery processing off and readiness degraded. The application never automatically copies restored
records into the new epoch.

The reconciliation state machine is `required -> reconciling -> suppressing -> ready`, with failure
remaining resumable and fail-closed. It requires provider execution and worker processing disabled,
suspends restored Topstep integrations, erases encrypted credentials and sessions, revokes approval
and attestation evidence, kills runs, cancels commands, terminally suppresses outbox work, records a
correlation-bound restore event, and only then advances the database epoch. This one-user beta
requires re-onboarding and new approval; prior access is never revived. Railway cannot automatically
prove that a restore occurred, so the runbook requires incrementing the environment epoch before
restored services process work.

### Failure and race invariants

The PostgreSQL suite contains two actual concurrent renewal lease/takeover tests plus a parameterized
set of 40 fail-closed lifecycle/restore invariant scenarios. The 40 scenarios do not each create a
separate concurrent database interleaving; full PostgreSQL race-matrix completion remains open. Real
row locks and partial uniqueness serialize renewal and active-account authority; `SKIP LOCKED` remains
the outbox claim mechanism. Deterministic failures before validation, after
response, after encryption, during audit persistence, before/after session commit, during lifecycle
changes, during restore suppression, and around epoch advancement leave invalid generations
non-executable. An acknowledgement loss after a committed renewal or epoch advance is idempotent
success, never a reason to restore prior state.

## Hosted risk policy, consent, and dry-run boundary

The hosted Combine policy is an operator-owned, versioned row bound to tenant, cohort, tester,
integration, and the exact currently approved Topstep account. There are no financial/instrument
defaults: missing values, empty allowlists, stale/revoked policy, and unknown state deny. The
initial execution-capability flag is constrained false by schema and startup checks. A policy
update increments its version; queued dry runs from older versions are fenced/canceled, prior
consent and proposals are invalidated, and running workers recheck under the integration lock.
The fixture policy is test-only and must not be copied as an owner-selected deployment limit.

The tester's explicit `hosted-combine-dry-run-v1` consent records the exact text version and binds
tenant, user, integration, credential generation, account approval, policy version, and correlation
ID. Consent confirms the account is represented as a Trading Combine (not Express or Live Funded),
acknowledges evaluation consequences and user responsibility, and states that current dry run sends
no order. It is not a waiver of product security obligations.

Dry runs are database work items claimed by the durable worker with leases/fences. The HTTP route
only requests and reads state. A proposal (if every required read-only snapshot exists and all checks
pass) uses a separate dry-run-only table; it has no provider-order identity and cannot be consumed
by an order worker. It never creates provider orders/fills/positions or ledger/P&L mutations. A
future execution feature must submit a new separately authorized durable command and reevaluate all
eligibility and risk state. At this checkpoint the Topstep-backed order/position/P&L/reconciliation
snapshots are not wired into dry-run evaluation, so those checks deny/degrade and no executable or
release-qualified proposal is claimed.

Risk decision table: missing/inconsistent tenant, integration, credential, session, epoch, approval,
policy, consent, cohort, run, or recovery state denies; stale data, cooldown, schedule violation,
kill switch, non-allowlisted strategy/instrument, quantity/position/loss/order limit failure denies;
provider/reconciliation/recovery data unavailable returns degraded; integrity failure returns
failed. Each result is stored as a safe independent check and never as an order acknowledgement.

## Deployment artifacts and preflight

The Vercel artifact serves only the frontend and has an explicit replace-before-deploy CSP API host
placeholder. Railway configuration separates API, worker, PostgreSQL, and Redis; the worker owns
durable work and migrations are a controlled release step. `scripts/hosted_beta_preflight.py`
validates deployment profile, secret separation and lengths, monotonic epoch, exact origins, service
URLs/roles, hosted key provider, disabled trading/mutations, and an active complete policy bound to
the configured tester/cohort. It reports names and classifications only, never secret values. A
post-build scan checks frontend assets for configured secret values. The preflight intentionally
fails in an unconfigured local environment; passing it is not proof of Vercel/Railway deployment.
