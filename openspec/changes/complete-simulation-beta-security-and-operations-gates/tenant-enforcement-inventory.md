# Universal Tenant Enforcement Inventory

Checkpoint: 2026-09-22. Scope: tasks 2.1-2.4 and every route mounted by
`app/main.py`, worker entry point, account lifecycle path, and repository/service
used by the invite-only simulation surface.

## Resource classification

| Resource family | Models / records | Ownership | Required access port |
| --- | --- | --- | --- |
| identity/session | `User`, verification/reset tokens, `UserSession`, recovery requests | user/tenant; pre-auth token lookup is an identity-bootstrap exception | authenticated `TenantContext`; pre-auth allowlist for token/session validation |
| integrations/secrets | `PlatformIntegration` | `user_id` | `TenantRepository`; encrypted secret service after scoped lookup |
| admission/onboarding | redemption, beta status, waitlist, onboarding, support, legal acceptance | `user_id` | `TenantRepository`; purpose-bound operator target for support/admin changes |
| subscription | subscription status and entitlements | `user_id` | `TenantRepository`; global plan catalog is not tenant owned |
| strategy/risk/safety | configurations, signals, settings, daily state, kill switches, decisions, lockouts, launch acknowledgements/evaluations | `user_id` | bound tenant session plus repository request access |
| simulation control | runs, leases, commands, checkpoints | `user_id` | `TenantRepository` for requests; verified job context plus fence for workers |
| simulation input/evaluation | market inputs, evaluations, run risk counters | `user_id` | signed-job tenant, run, lease, and fence |
| simulated accounting | orders/events/fills/positions/snapshots/ledger | `user_id` | bound tenant session; automated writes also require current fence |
| reconciliation | runs/events/retry decisions/locks | `user_id` | bound tenant session and repository request access |
| delivery | outbox event and delivery | direct `user_id` after `fc3f4a5b6c7d` | verified job context; tenant-inclusive event relationship |
| lifecycle | deletion request, revocation attempt, tombstone | direct `user_id` after `fc3f4a5b6c7d` | authenticated tenant; restore drill is offline-only |
| audit | `SecurityAuditEvent` | actor/target pair, append-only | repository audit-history method or operator audit append service |
| analytics | `AnalyticsEvent` | nullable `user_id`; anonymous events are non-tenant | tenant repository for user events; target-bound operator aggregation |
| global metadata | legal documents, plan tiers, beta invite codes, rate buckets | system/global | narrow `OperatorRepository` allowlist or public read service |

## Access-path migration matrix

| Entry point | Resource | Tenant / actor source | Enforcement and repository | Error behavior | Classification / result |
| --- | --- | --- | --- | --- | --- |
| authenticated route dependency | all request tenant data | validated JWT + active session; actor=user | immutable context bound to the shared request session; ORM scope and flush guard | 401 before route | Beta-reachable / migrated |
| `/integrations*` | integrations and credentials | authenticated context | `TenantRepository` get/list/add; services inherit bound scope | tenant miss = 404 | Beta-reachable / migrated |
| `/simulation-runs*` | run, command, market input, status | authenticated context | repository status reads; durable command/input services bind same context | tenant miss = 404 with common response | Beta-reachable / migrated |
| `/scheduler/bot-sessions`, stop alias | durable run/command | authenticated context | durable service binds context; database state remains authoritative | tenant miss = common rejection | Beta-reachable / migrated |
| `/scheduler/run-bot` | status-only SSE | authenticated context at subscription; fresh scoped session in stream | repository lookup before response and in status generator | tenant miss = 404 | Beta-reachable / migrated; SSE owns no execution |
| `/risk*` | settings, decisions, kill and affected runs | authenticated context | repository ownership/read/list/lock plus existing risk service under bound session | integration/run miss = 404 | Beta-reachable / migrated |
| `/reconciliation*` | reconciliation evidence | authenticated context | repository get/list; service inherits scope | miss = 404 | Beta-reachable / migrated |
| `/launch-gate*` | readiness and acknowledgements | authenticated context | repository get/list; launch service inherits scope | miss = 404 | Beta-reachable / migrated |
| `/auth/account/export` | every `user_id` model + safe audit | authenticated context | dynamic repository list and scoped audit-history port | only caller tenant appears | Beta-reachable / migrated |
| deletion request/execute/cancel | lifecycle, sessions, credentials, tombstone | authenticated context + password | repository get/list/update; flush guard prevents foreign effects | foreign and absent request = same 404 | Beta-reachable / migrated |
| `/onboarding/support*` | support tickets | authenticated or operator context | repository; operator target is bound before access | miss = 404 | Beta-reachable / migrated |
| `/analytics/admin*` | target analytics/aggregates | operator actor + purpose + case + target + five-minute expiry | operator context replaces actor scope for one request; services are auto-scoped | 403 authorization; no target data | Operator-only / migrated |
| subscription admin | target profile/subscription/entitlement | target-bound operator context | target tenant repository; no global user fetch | foreign target = 404/403 | Operator-only / migrated |
| invite catalog administration | global invite metadata | purpose-bound operator | explicit `OperatorRepository.GLOBAL_MODELS` allowlist | 403 without context | Operator-only / isolated global metadata |
| durable recovery discovery | expired runs | worker system identity | `system_maintenance_scope('durable-recovery-discovery')` returns IDs, then each run requires signed envelope | invalid envelope has common safe failure | Internal maintenance / migrated |
| command/input/outbox discovery | pending work | worker system identity | four named discovery purposes only; every effect validates signed tenant envelope | forged/substituted context rejected before effect | Internal maintenance / migrated |
| durable execution/recovery | all execution/financial records | verified envelope, then tenant/run/fence | bound context plus existing fence, reconciliation, and idempotency | stale/foreign = safe failure | Beta worker / migrated |
| registration/login/verification/reset | identity bootstrap | credential or opaque single-use token | architectural allowlist; token hash/global identity lookup only, uniform invalid response | does not disclose tenant records | Public auth / isolated exception |
| `/trading/webhook` | legacy signal fixture | none in old design | now returns 404 outside `APP_ENV=test` before global integration lookup | same unavailable response | Development/test only in hosted beta |
| demo/reseed and test fixtures | representative tenant data | explicit local fixture | unbound/offline session allowlist; production config prevents fixture header | not production reachable | Development/test only |
| Alembic and deletion/restore drill | schema/offline bundles | offline operator/process | explicit scripts, no request router | fail/abort on mismatch | Migration/offline |

## Trusted-context contract

`TenantContext` is immutable and contains tenant, actor, session/job identity,
roles, permissions, source, request/correlation/causation identifiers,
creation/expiry, and integrity state. Session context is created only after JWT,
active-session, CSRF (for cookie mutation), and active-user validation.

`VerifiedTenantJob` v2 signs canonical tenant, actor, stable job ID, job type,
purpose, issuer, environment, issue/expiry, correlation/causation, payload hash,
nonce, and version. Validation compares the expected durable record identity and
environment. Replay is allowed only as idempotent redelivery of the same durable
job; command/evaluation/outbox uniqueness prevents a second effect.

`OperatorContext` requires operator identity, target tenant, meaningful purpose,
case, exact action, correlation ID, and a server-issued five-minute expiry. A
path `user_id` must equal the authorized target. It replaces an authenticated
actor scope only after the authorization decision is durably audited.

## Repository and guard rules

- `TenantRepository` requires context in its constructor and exposes get, list,
  count, existence, insert, update, delete, lock, pagination, aggregate, user,
  and audit-history values; it never returns `Query` or `Session`.
- Bound sessions apply tenant loader criteria to ORM SELECT/UPDATE/DELETE and
  reject cross-tenant new/dirty/deleted objects before flush. This protects
  legacy service internals while their APIs remain compatibility adapters.
- Tenant switching is rejected except a newly authorized operator context or a
  distinct verified job envelope. Client fields never invoke either path.
- `OperatorRepository` permits global reads only for the reviewed global model
  set: invite code, plan tier, and legal document.
- Worker-wide discovery is limited to four named purposes. Request modules do
  not import the system maintenance scope.

## Direct ORM disposition and architectural allowlist

The syntax-aware CI guard rejects direct `.query()` in mounted request modules.
The only function allowlist is:

- `auth_routes.py`: username/session/token bootstrap, registration,
  verification, reset, and recovery functions which execute before tenant
  authentication and return uniform failures;
- `trading_routes.py:receive_signal`: retained only for `APP_ENV=test`; hosted
  environments return 404 before its legacy lookup.

Service modules still contain ORM implementation queries, but beta request
access reaches them only through a context-bound session. Durable worker modules
retain ORM transaction code because fencing and atomic financial writes are
infrastructure operations; every effect is preceded by verified job binding.
Offline scripts, migrations, and tests are outside request serving. Removing the
legacy test-only webhook and converting compatibility services into narrower
repositories remain post-slice cleanup, not beta authorization gaps.

## Database constraint inventory

Migration `fc3f4a5b6c7d` adds non-null tenant ownership to outbox deliveries and
provider revocation attempts, backfills from their authoritative parent, aborts
if any row cannot be derived, and adds tenant-inclusive foreign keys. It also
adds tenant-leading indexes for simulation runs, commands, market inputs,
evaluations, checkpoints, paper orders, fills, and ledger records. Existing
tenant-scoped uniqueness remains on durable commands, market/evaluation,
orders/fills/ledger, and checkpoints.

PostgreSQL RLS was not added: the current application role/session model does
not yet establish transaction-local tenant variables, so ceremonial RLS could
be bypassed. Repository/session enforcement plus directly verified composite
relationships is the enforceable design for this deployment shape.

## Residual risk

- Pre-auth identity bootstrap remains a deliberately narrow system lookup and
  depends on rate limiting and uniform token/credential errors.
- Legacy services are protected by the bound-session guard but are not all
  mechanically rewritten into repository calls; the architectural guard blocks
  request-route regression and the compatibility layer is documented.
- Managed backup purge and restore infrastructure are owner-controlled and not
  proven by this slice.
- Host branch protection has not been observed; the CI definition alone is not
  host evidence.
