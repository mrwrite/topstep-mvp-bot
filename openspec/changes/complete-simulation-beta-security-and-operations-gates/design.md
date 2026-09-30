## Context

## Hosted Trading Combine dry-run/risk continuation (2026-09-29)

The active child slice adds a tenant-bound versioned hosted risk-policy contract, exact-text tester
consent, durable dry-run/proposal records, API/worker role separation, and Vercel/Railway templates.
Provider mutation capabilities remain disabled. Policies do not receive production numeric defaults;
owner/operator-selected instruments, schedules, and risk thresholds remain required before the
hosted readiness gate can pass.

The dry-run worker currently consumes existing tenant-owned persisted market input and revalidates
generation, approval, consent, policy, security epoch, and fencing. It intentionally classifies the
work degraded when authoritative Topstep read-only market/risk/reconciliation evidence is unavailable;
the current code has no verified source for these provider risk snapshots. Therefore it must not be
interpreted as full Topstep connectivity, an accepted order, or a Combine-readiness pass. Vercel and
Railway artifacts are templates only and do not establish deployment evidence.

The current FastAPI/SQLAlchemy application has secure cookie sessions, CSRF validation, server-derived user identity, purpose-bound operator authorization, encrypted integration credentials, database rate limits, durable paper-order/risk/reconciliation evidence, and hard live-trading rejection. External simulation beta remains blocked because credential encryption is tied to one application Fernet key, tenant enforcement is not structurally mandatory everywhere, bot ownership is process-local, operator evidence stops at authorization, deletion/backup restore protection is untested, warnings are uncontrolled, and release operations lack host evidence.

Owner decision 2026-09-23 selected a self-hosted Raspberry Pi with a physical TPM 2.0 and prohibited AWS and cloud KMS products. Owner decision 2026-09-24 changes the immediate target to a one-user Topstep Trading Combine beta with a Vercel frontend and separate Railway API, worker, PostgreSQL, and Redis services. Physical TPM evidence is deferred and non-blocking only for that hosted stage; it remains required for the planned self-hosted profile and future live/live-credential readiness unless separately reconsidered.

## Goals / Non-Goals

**Goals:**

- Make a small invite-only, local-simulation-only cohort safe across secrets, tenant isolation, execution recovery, deletion, reproducibility, quality, and operations.
- Keep committed execution intent and event publication atomic and idempotent.
- Make every release claim traceable to automated or owner evidence.
- Preserve `rsi-threshold-v1`, demo behavior, risk controls, reconciliation locks, kill switches, and paper/live separation.

**Non-Goals:**

- Brokerage adapters, broker paper accounts, market-data entitlements, or live-money execution.
- Provisioning or claiming evidence for physical hardware not present in this environment; branch rules, legal documents, staffing, and commercial approvals also remain owner-controlled.
- Profitability claims or treating hypothetical fills as future returns.

## Decisions

### 1. TPM-backed local envelope encryption

`KeyManagementProvider` wraps and unwraps randomly generated per-record data-encryption keys. Schema-2 envelopes use AES-256-GCM with unique 96-bit nonces and immutable canonical AAD for tenant, purpose, record type/ID, environment, and schema. Mutable wrapping-key ID/version, wrapped-key bytes, context hash, and recovery wrap are authenticated by a DEK-derived HMAC so rotation can rewrap only the DEK without AES-GCM nonce reuse or plaintext re-encryption.

A visibly named local provider is development/test only. Production explicitly requires `tpm2`, `/dev/tpmrm0`, a persistent RSA-2048 OAEP-SHA256 key, approved public fingerprint, safe runtime authorization-file permissions, recovery public key, and successful self-test. Private TPM and recovery keys never reside in files, environment, database, image, backup, or repository. Missing/retired keys, identity mismatch, software TPM, lockout/auth failure, unsafe permissions, provider outage, tampering, and context mismatch fail closed with sanitized codes.

TPM2-TSS through `tpm2-tools` is the initial adapter; direct TPM subprocess calls are confined to that boundary. PKCS#11 adds unnecessary token-store/PIN lifecycle for this slice; a Python TPM binding lacks demonstrated target compatibility. PCR binding is deferred because an untested policy would make ordinary Pi firmware/boot/kernel/container upgrades fragile. Physical possession, fixed TPM/object attributes, authorization, device permissions, fingerprint pinning, and self-test are the initial controls.

### 2. Mandatory tenant ports

`TenantContext` is required by tenant repositories and verified job envelopes. HTTP context comes only from the authenticated session; jobs persist tenant ID plus an integrity/version marker; operators use the existing actor/purpose/case/target context. Resource misses and cross-tenant IDs both return the same not-found response. Architectural tests enumerate beta routers/services and reject direct unscoped tenant-owned queries outside approved repository modules.

Alternative rejected: relying on developer convention and repeated `filter(user_id=...)`.

### 3. Persisted, fenced simulation state machine

`SimulationRun`, `SimulationCommand`, `SimulationCheckpoint`, `SimulationLease`, `OutboxEvent`, and `OutboxDelivery` are durable. State transitions are compare-and-set against state version and fencing token. A lease has owner, monotonically increasing fence, expiry, and renewal timestamp. Expired leases can be taken over; stale owners cannot checkpoint, transition, emit intent, or acknowledge outbox work.

Commands have tenant-scoped idempotency keys and terminal outcomes. A transaction commits the state/intent/checkpoint and outbox event together. Consumers claim events with leases, use unique consumer/event keys, and record success, retry time, or terminal dead-letter status. Recovery first checks kill switches, reconciliation locks, checkpoints, and outstanding commands, then moves `Recovering` to a safe state without generating an order by recovery alone.

#### Authoritative transition table

| From | Cause | To | Authority |
| --- | --- | --- | --- |
| Requested | start | Starting | command transaction |
| Starting | safety validation | Running | active lease/fence |
| Running | pause | Pausing | command transaction |
| Pausing | safe checkpoint | Paused | active lease/fence |
| Paused | resume | Starting | command transaction; reacquire |
| Running/Paused/Pausing | stop | Stopping | command transaction |
| Stopping | safe checkpoint | Stopped | active lease/fence |
| Starting/Running/Pausing/Stopping | owner loss | Recovering | takeover fence |
| Any nonterminal | kill | Killed | lease-independent kill transaction |
| Recovering | reconciled | Running/Paused/Stopped/Killed | takeover fence |
| Any nonterminal | unsafe recovery | Failed | fenced/recovery transaction |

Killed, Stopped, and Failed are terminal. Repeated tenant command keys return the original outcome; repeated stop and kill may complete as durable no-ops. Kill supersedes every other command.

#### Lease, checkpoint, outbox, and recovery invariants

Every execution-side state, checkpoint, simulated-order intent, fill, ledger, and outbox write MUST match tenant, run, and current fencing token. Takeover monotonically increments the fence. A checkpoint is a safe evaluation boundary containing market identity, configuration hash/version, strategy version/state, deterministic seed, risk counters, pending intent IDs, position/ledger version, simulation clock, and last event identity.

Database uniqueness supplies exactly-once command keys, checkpoint sequences, outbox consumer deliveries, and simulated-order idempotency keys. Delivery is otherwise effectively-once through durable intent, redelivery, idempotent effects, and reconciliation. Published does not mean consumed.

Recovery checks kill first. Missing or incompatible checkpoints, configuration/strategy mismatches, or unreconcilable domain state fail closed. Valid checkpoints may restore the documented desired state; stale data pauses/degrades; recovery alone never emits an order. Workers check kill before acquisition, after takeover, at renewal, and before execution effects.

#### Durable evaluation transaction

`SimulationMarketInput` is the only scheduled-input boundary. Its stable source
identity is the SHA-256 digest of source, normalized instrument, timeframe,
UTC event timestamp, and provider sequence. A separate content digest detects
conflicting revisions. The worker classifies an input as new, duplicate, stale,
out of order, conflicting, missing a predecessor, or too old. HTTP may enqueue
an input but cannot evaluate it.

For a new input, one PostgreSQL transaction locks the run and lease and verifies
tenant, environment, run state, fence, kill switches, reconciliation lock,
configuration hash, strategy version, schedule, market freshness, and the prior
checkpoint. It then:

1. computes `rsi-threshold-v1` from the canonical lookback;
2. appends a uniquely identified evaluation and rationale;
3. persists a risk decision;
4. optionally creates a distinct simulated-order submission;
5. applies documented slippage and fees to a separately persisted simulated fill;
6. updates position, account snapshot, daily/run risk counters, and one uniquely
   identified ledger effect;
7. appends outbox events; and
8. commits an integrity-hashed checkpoint.

Any exception before commit rolls back every effect. Kill and evaluation both
lock the run, so their transactions have a database-defined order: kill first
rejects evaluation; an evaluation transaction which acquired the run first may
commit completely before kill, after which no later effect can commit.

#### Checkpoint contract

Each checkpoint contains the last market and evaluation identities, market
content hash, strategy state/version, immutable configuration hash, simulation
clock, deterministic seed, run/daily risk counters, position state/version,
account state/version, ledger count, pending intent IDs, last order/fill/event
identities, and freshness classification. SHA-256 over canonical JSON excludes
the digest field itself. Recovery validates both the stored digest and the run's
last-digest pointer.

#### Financial and replay invariants

| Invariant | Enforcement |
| --- | --- |
| one evaluation per run/input boundary | unique run/evaluation identity and locked input |
| one automated order per evaluation | tenant idempotency key |
| fill references an order and cannot overfill it | foreign key plus reconciliation checks |
| fees/slippage apply once | one unique ledger identity per fill |
| position equals reconciled fills | checkpoint and recovery recomputation |
| risk trade count equals committed fills | run risk counter/checkpoint reconciliation |
| stale owner changes no economic state | run-row fence check inside the economic transaction |
| killed run emits no later effect | kill increments fence and makes the run terminal |

The database provides exactly-once uniqueness for command keys, market source
identities, evaluation identities, order keys, fill identities, ledger
identities, checkpoint sequences, and consumer/event outcomes. Worker delivery
is at-least-once. End-to-end effects are effectively-once through those
identities, fencing, atomic transactions, redelivery, and reconciliation; the
system does not claim global exactly-once execution.

#### Recovery decision table

| Condition after fenced takeover | Decision |
| --- | --- |
| durable run or matching scope kill active | Killed |
| configuration/strategy/checkpoint digest mismatch | Failed |
| order/fill/position/ledger/risk/market disagreement | Failed |
| stale, out-of-order, too-old, or unknown last input | Paused/degraded |
| desired pause with reconciled checkpoint | Paused |
| desired stop with reconciled checkpoint | Stopped |
| desired run with reconciled fresh checkpoint | Running |
| no checkpoint for an interrupted Starting run | perform start validation only; emit no order |

#### Kill timing

| Timing | Result |
| --- | --- |
| before lease/evaluation/recovery | fence acquisition/effect rejected |
| while an evaluation transaction owns the run lock | evaluation commits atomically first or rolls back; kill commits next |
| after order intent but before fill/ledger/checkpoint | no visible partial state because all are one transaction |
| before takeover | takeover is rejected as terminal |
| after old owner loses fence | every old-owner effect is rejected |
| during outbox redelivery | audit delivery may finish idempotently but cannot resume or execute a killed run |
| process restart | persisted Killed state and advanced fence remain authoritative |

### 4. Operator action scope

Operator middleware creates an authorization-decision event. `OperatorAction` creates append-only `started` and terminal `succeeded`, `failed`, `partial`, or `cancelled` events sharing a correlation ID. Safe summaries are allowlisted and redacted. Ordinary application roles have no update/delete API for audit rows.

### 5. Deletion tombstones protect restores

Deletion creates a durable tombstone containing non-secret identity hashes, tenant ID, execution time, purge eligibility, and retention/hold state. Backup manifests include tombstones. Restore applies data then reapplies all non-expired tombstones, deleting/anonymizing resurrected identity, sessions, and encrypted credentials. A non-production drill operates on an isolated SQLite bundle and produces JSON and Markdown evidence.

### 6. Warning budget is counted, not hidden

Application deprecations are fixed where safe. Narrow filters require code, owner, reason, and expiry. Pytest emits a machine-readable warning summary; CI fails if category/source counts exceed the committed baseline or any unapproved warning appears. The target is zero application-owned actionable warnings.

### 7. Release evidence is a signed-by-process manifest

Verification commands write a JSON manifest with command, exit status, duration, revision, environment, counts, and artifact hashes. CI uploads it. Repository documentation defines required branch checks, but the gate stays open until the host confirms protection and a green run.

### 8. Simulation operations use conservative configurable defaults

Application code enforces a configurable cohort cap and invitation revocation, simulation-only environment, maintenance/suspension flags, health state, and critical-incident veto. Support owner/hours, legal acceptance, retention policy, and final cap require explicit owner values; missing production values block admission.

### 9. Trusted tenant contexts and guarded persistence

The request trust boundary constructs immutable `TenantContext` only after JWT,
active session, CSRF where applicable, and active-user validation. The context
contains tenant, actor, session/source, role/permissions, request/correlation/
causation, issue/expiry, and integrity state. It is bound to the SQLAlchemy
session shared by request dependencies. Binding a different tenant fails unless
the replacement is a newly authorized operator target or a distinct verified
job envelope.

`TenantRepository` is the request-facing port and never returns a raw session or
query. SQLAlchemy execution criteria and a before-flush guard provide defense in
depth for compatibility services: reads/updates/deletes are scoped and new,
dirty, or deleted tenant objects must match the bound tenant. Pre-auth token and
identity bootstrap is explicitly allowlisted and uses uniform errors.

`VerifiedTenantJob` v2 signs tenant, actor, job ID/type, purpose, issuer,
environment, issue/expiry, correlation/causation, payload digest, nonce, and
version. The consumer compares every expected field to its durable record.
Redelivery is at-least-once, while stable durable identities make replay
idempotent; the signature itself is not described as an exactly-once mechanism.

### 10. Operator and system-level access are distinct ports

`OperatorContext` is actor-, action-, purpose-, case-, target-, correlation-,
and expiry-bound. It may replace the actor's ordinary tenant binding for one
request only after an append-only authorization event commits. Tenant data then
uses the normal tenant repository. `OperatorRepository` exposes only the
reviewed global metadata models (invite code, plan, legal document); it is not a
global tenant repository.

Worker discovery is the only cross-tenant application operation. Four named
system-maintenance purposes discover expired runs, accepted commands, pending
market inputs, and claimable outbox events. Discovery returns work identities;
every subsequent effect establishes a signed tenant context and retains the
existing run/fence checks. Request modules cannot use this port.

### 11. Stream and lifecycle isolation

Polling and the compatibility SSE endpoint authenticate before the first lookup
and query durable status through a tenant repository. SSE is status-only and
owns no execution. No WebSocket route exists. A reconnect repeats authentication
and ownership lookup; a foreign and nonexistent run both return 404.

Export enumerates tenant-owned models only through repository lists and uses a
special actor/target-scoped audit-history method. Deletion execute/cancel uses a
tenant-scoped request lookup before revocation, session, credential, identity,
or tombstone effects. Outbox deliveries and provider-revocation attempts now
carry non-null tenant IDs and tenant-inclusive PostgreSQL foreign keys, closing
the prior indirect-ownership gap.

### 12. Architectural and database guardrails

A syntax-aware architectural test scans every mounted request module and fails
for direct ORM queries outside the documented pre-auth/test-only allowlist or
client-derived context construction. Allowed and prohibited fixture sources are
tested. Migrations/offline scripts, repository implementation, durable atomic
infrastructure, and tests are explicit non-request categories.

Migration `fc3f4a5b6c7d` aborts if legacy delivery/revocation ownership cannot be
derived, adds direct ownership and composite parent relationships, and adds
tenant-leading hot-path indexes. PostgreSQL RLS was rejected for this slice
because the current shared application role does not set a reliably verified
transaction-local tenant; RLS that the role could bypass would be ceremonial.

The full inventory, exception rationale, and removal notes are in
`tenant-enforcement-inventory.md`; the 48-row evidence map is in
`cross-tenant-negative-matrix.md`.

## Risks / Trade-offs

- **Physical TPM evidence is unresolved** → production startup fails closed; abstraction, mock, and software-TPM tests do not count as hardware completion.
- **Database leases depend on database availability** → fail closed, stop renewal, and recover only after a new fenced lease.
- **Architectural tenant checks can produce false positives** → keep a reviewed allowlist with explicit reasons and tests.
- **Restore drills are not a managed-backup game day** → report them as application-level evidence only; owner infrastructure drill remains open.
- **Warning cleanup can reveal dependency constraints** → budget narrowly and never globally ignore security/runtime warnings.
- **Large state-machine scope can regress paper behavior** → route simulation commands through new durable records while retaining current paper execution and its regression suite.

## Migration Plan

1. Add physical-TPM provider configuration and explicit migration-only legacy reads without deleting legacy ciphertext.
2. Add tenant/audit/run/lease/command/outbox/checkpoint/tombstone tables in one linear Alembic revision.
3. Backfill legacy simulation sessions as stopped records only; never auto-resume.
4. Switch start/pause/resume/stop paths to durable commands; keep live rejection unchanged.
5. Deploy with simulation admission disabled, run migration/recovery/deletion drills, then enable only after all application and owner gates pass.
6. Roll back application code while retaining additive tables and envelopes; old credential reads remain available only during an explicitly bounded migration window.

## Open Questions

- Which Pi/TPM model, persistent handles, authorization delivery, recovery custodian, and 30-day rollback/retirement approvals will the owner approve?
- What cohort cap, support owner/hours, retention period, and legal documents are approved?
- Which repository-host branch rules and evidence-retention duration will be configured?
- What recovery objectives and managed-backup purge capabilities are available?

## TPM trust boundary and recovery threat model

The database/backup contains only versioned ciphertext plus TPM and recovery public-key wraps. The Pi contains public metadata and a TPM handle. The TPM alone contains the non-exportable production private key. The encrypted offline recovery private package, its passphrase, and database backups have separate custody. Theft of only one of the database, Pi storage, or recovery package is insufficient; a compromised running host can still request authorized unwraps and remains a residual risk. Single-owner recovery custody is an explicit risk awaiting owner approval.

## Rotation and cutover state machines

Rotation is `planned -> active-write -> rewrapping -> verifying -> ready-to-retire -> completed`, with `paused` and `failed`. Fernet migration is `inventory -> dry-run -> backed-up -> migrating -> verifying -> envelope-only -> rollback-retention -> destruction-approved`. PostgreSQL workers claim records with row locks, commit idempotently, and reconcile counts. Envelope-only cutover requires zero active Fernet rows, per-record verification, restored-backup evidence, and proof that legacy ciphertext is rejected.

## Key-retirement decision table

| Gate | Required result | Missing result |
|---|---|---|
| exact identity | handle, TPM name, fingerprint, version match | reject |
| active records | authoritative zero dependency | reject |
| backups | dependency inventory and restore verification | reject |
| recovery | replacement-TPM drill reconciles all records | reject |
| rollback | approved window and implications | reject |
| approval | named owner confirms destructive target | reject |

## Production startup and hardware evidence matrix

Startup rejects absent TPM resource-manager access, missing handle, fingerprint mismatch, software/emulated providers, development/file/environment keys, recovery private material, unsafe permissions, legacy key after cutover, unsupported envelope policy, or failed self-test.

| Evidence | Mock/software status | Physical status |
|---|---|---|
| context/tamper/algorithm failures | covered by deterministic tests | not a hardware claim |
| TPM commands/failure mapping | covered by command adapter double | open |
| object attributes/non-exportability | not closable | open |
| container restart/Pi reboot/upgrade | not closable | open |
| outage/lockout/rotation | behavior modeled | open |
| restored-backup replacement recovery | algorithm modeled | open |

Every physical cell remains open until evidence from the production-model Raspberry Pi and discrete TPM is attached.

## Hosted Trading Combine beta trust boundary

The Vercel deployment contains frontend assets and an explicitly public Railway API URL only. Railway holds an explicitly named `railway-secret-envelope-v1` service variable, runs FastAPI and the fenced durable worker as separate services, and uses PostgreSQL as the sole authoritative store; Redis is non-authoritative. Railway administrators and a compromised authorized runtime can access the hosted root key. The owner accepts that limitation only for one invited tester, one attested and administratively approved Trading Combine account, simulated provider selection, conservative server-owned risk limits, and server-side live rejection. It is not TPM-equivalent and is not approved for Express Funded, Live Funded, or live brokerage use.

Release governance distinguishes internal software testing, invite-only internal simulation, one-user Trading Combine beta, Express Funded beta, and Live Funded/live-brokerage beta. A Combine is simulated execution but can affect evaluation status, account-rule compliance, and subscription value; current consent and successful read-only dry-run evidence are required before provider submission is enabled. The authoritative implementation child is `deploy-invite-only-topstep-combine-beta-to-vercel-and-railway`.

## Durable Topstep onboarding and deletion checkpoint

The hosted child now owns a database-authoritative lifecycle for one Topstep integration. Separate tenant tables store credential generations, encrypted expiring sessions, safe discovery snapshots, discovered account rows, versioned Combine attestations, exact operator approvals, and terminal tombstones. Tenant-inclusive foreign keys and partial unique indexes enforce one current credential generation and one active approved account. Account names are display-only.

Encrypted session persistence was selected over process-local authority so API/worker restarts retain session expiry/generation facts. At the initial onboarding checkpoint, expiry failed closed and renewal was still open; the later durable session continuation now validates and rotates through the official endpoint under a fenced lease and permits reauthentication only after explicit invalid-session rejection for the current generation. Replacement authenticates first, then atomically invalidates the old generation. Disconnect and deletion suppress matching active runs, commands, and outbox work before secret erasure. Legacy configured/first-account selection and direct Topstep order submission are disabled. The centralized eligibility service produces typed decisions but cannot submit an order.

This checkpoint does not provide Railway/Vercel deployment, provider sandbox, real credential, dry-run, restore, or order evidence, and does not alter physical TPM requirements for self-hosted or future live profiles.
## Hosted session and database-restore authority

For the explicitly scoped hosted Combine profile, encrypted Topstep session rows—not adapter
process caches—are authoritative. Renewal uses expiring database leases and monotonic fences; every
commit binds tenant, integration, current credential generation, session generation, and the hosted
security epoch. Replacement, revocation, deletion, and restore reconciliation always defeat stale
renewal results.

Because a restored database can predate its own tombstones, hosted restore safety also depends on
the external, non-secret, monotonic `HOSTED_SECURITY_EPOCH`. An epoch mismatch makes all restored
authorization and credential-dependent work non-executable. The operator must run a disabled-worker,
disabled-provider revoke-by-default reconciliation and require fresh onboarding/approval. This does
not replace TPM requirements for the self-hosted/future-live profile and does not claim Railway
backup-platform evidence.
# Hosted Trading Combine risk and dry-run checkpoint — 2026-09-29

The hosted-only extension adds a tenant/cohort/tester/integration/account-bound versioned risk
policy and consent. Missing or empty policy state denies. The browser cannot set policy limits, and
provider mutations remain disabled. A durable leased worker evaluates dry runs using application
eligibility and strategy paths; proposals, where complete read-only snapshots permit them, are
stored separately as `dry_run_only` and cannot become orders. Current provider-backed order,
position, P&L, and reconciliation snapshots are unavailable, so those checks fail closed and no
provider readiness is claimed. This hosted configuration does not remove the deferred TPM
self-hosted requirement or authorize funded/live brokerage accounts.
