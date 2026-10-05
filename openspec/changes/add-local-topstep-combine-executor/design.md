## Context

The application currently runs FastAPI and a durable worker on Railway. Its `TopStepXAdapter` supports authentication, account discovery, simulated contract/history lookup, and session handling, but startup checks and adapter methods deliberately reject every provider mutation. The active hosted-Combine design proposed making the Railway worker authoritative for provider orders.

Topstep's current API policy changes that deployment assumption. Automated trading is allowed, but trading activity and any automated trigger that can reach order endpoints must originate from the trader's personal device. VPS and remote-server placement, modification, cancellation, routing, or relaying are prohibited. Topstep explicitly permits a remote server to perform read-only supporting work such as analytics and receiving copies of fills, positions, and P&L. The Gateway has no sandbox; Topstep directs users to a Practice account for safe API testing.

The ProjectX REST API provides documented simulated-account contract selection with `live: false`, order placement with a caller-supplied `customTag`, order search, trade search, open-position search, cancellation, modification, and position close. Order placement can return pending or unknown outcomes, and the API enforces separate limits for history and other endpoints. Those facts require local durable intent recording and reconciliation rather than request-level retry.

The initial stakeholder is one invited Windows or macOS user operating one personal computer, one dedicated Topstep API key, one Practice account, and one exact Trading Combine account. Railway/Vercel remain useful for authentication, a read-only dashboard, support diagnostics, and sanitized telemetry, but they cannot participate in the causal chain that produces an order.

## Goals / Non-Goals

**Goals:**

- Make the user's personal computer the sole authority for strategy evaluation, risk decisions, Topstep credentials, provider sessions, and provider mutations.
- Support a controlled progression from observe-only to Practice qualification and then exact-account Trading Combine testing.
- Persist enough local state to reconcile ambiguous submissions, restarts, fills, positions, and kills without duplicate orders.
- Keep Railway and Vercel useful as an outbound-only telemetry destination and read-only dashboard while proving they cannot create or relay trading instructions.
- Reuse pure strategy and risk calculations where safe without importing hosted database, tenant, worker, or credential services into the local mutation boundary.
- Keep Express Funded, Live Funded, live brokerage, multi-user execution, and remote/headless execution unavailable.

**Non-Goals:**

- Real-money or Live Funded execution.
- Railway, Vercel, a hosted browser bundle, webhook, email, push message, or hosted scheduler triggering a local order.
- Multi-account trading, trade copying, unattended VPS operation, or remote desktop hosting.
- Inferring account type from account names; the provider response does not authoritatively classify Practice, Combine, or Express Funded accounts.
- High-frequency trading or latency-sensitive execution.
- Automatically running a real provider order in CI or during installation.

## Decisions

### Separate the mutation client from the hosted adapter

The existing `app.providers.topstepx.TopStepXAdapter` remains read-only and retains its hosted startup assertion. A new local-executor package owns a distinct `LocalTopstepClient` containing documented mutation endpoints. Hosted modules, Docker images, API routes, and Railway workers must not import that client. Architecture tests inspect imports and call graphs, and the local entrypoint refuses production/hosted profiles, Railway indicators, non-loopback control binding, and `SERVICE_ROLE=api|worker`.

This is preferred over enabling mutations on the shared adapter because a shared capability flag would make a configuration mistake sufficient to turn Railway into an order router. It duplicates a small amount of HTTP plumbing in exchange for a mechanically enforceable trust boundary.

### Run as an interactive personal-device application

The first supported runtimes are interactively launched Windows and macOS desktop applications. They are not installed as unattended services and do not accept inbound network connections. A local control surface may bind only to `127.0.0.1`, serves its own pinned static assets, validates Host/Origin, uses a per-launch anti-CSRF secret, and rejects non-loopback clients. The hosted frontend remains read-only and cannot call the local control surface.

The application records a local device installation identity for audit correlation, but it does not claim that software can cryptographically prove a machine is a personal device. Interactive launch requirements, hosted-environment rejection, documentation, and acceptance evidence reduce accidental noncompliance; the operator remains responsible for following Topstep's terms.

Alternatives rejected are a Railway worker, a hosted command queue consumed locally, and a remotely served browser UI that can invoke localhost. Each would let hosted state or code enter the causal order path and could constitute routing or relaying.

### Keep credentials local with OS-backed custody

The Topstep username and API key are entered only into the local application and stored through Windows Credential Manager or the current user's macOS Keychain using a dedicated OS-keyring integration. Provider session tokens remain memory-only and are renewed or recreated from the local credential; they are not persisted to SQLite. Logs, crash reports, telemetry, configuration files, command-line arguments, process titles, and browser storage cannot contain credentials or tokens.

The local SQLite database contains execution facts and exact provider identifiers but no authentication material. Its directory is created under the user's application-data directory with user-only permissions. Database backups are local, opt-in, and treated as sensitive even though credentials are excluded.

This supersedes hosted Topstep credential onboarding. Before Combine activation, any previously hosted Topstep credentials and sessions must be tombstoned/deleted and the user must rotate the dedicated API key.

### Use a local, fail-closed activation state machine

Execution progresses through `disabled`, `observe_only`, `practice_armed`, `practice_qualified`, `combine_pending`, `combine_armed`, `running`, and `halted`. State transitions are local durable records. Reinstallation, credential change, account change, policy change, binary/configuration integrity failure, clock drift, provider authentication failure, reconciliation ambiguity, stale data, or kill activation returns the executor to a non-ordering state.

Practice qualification requires a configured minimum observation window and order lifecycle evidence, including restart, timeout/ambiguity, cancel, reconciliation, risk rejection, and kill drills. Combine arming then requires:

- rediscovery and exact selection of one `canTrade` and visible account;
- explicit attestation that the selected ID is a Trading Combine and not Practice, Express Funded, or Live Funded;
- typed confirmation of a redacted account suffix;
- current versioned consent describing evaluation and subscription consequences;
- a complete local policy and a recent successful read-only preflight;
- no unexplained open orders, positions, or reconciliation locks; and
- short-lived local arming that expires on restart or after a configured interval.

The account API does not provide authoritative account type. Therefore attestation and exact-ID allowlisting are explicit residual controls, never name-pattern inference. The initial release permits quantity one and one exact account only.

### Make local SQLite the provider-action journal

A separate local SQLAlchemy metadata and Alembic chain store policy versions, consent, activation transitions, market-input identity, strategy decisions, order intents, submission attempts, acknowledgements, provider orders, trades, position snapshots, reconciliation runs, kills, and a sanitized telemetry outbox. SQLite uses WAL mode, foreign keys, an application-level single-writer lease, monotonic sequence numbers, and stable UUID identities. It does not reuse Railway/PostgreSQL execution tables as authority.

Before network submission, the executor commits an immutable intent containing the account, contract, side, order type, quantity, strategy/configuration versions, risk decision, and a stable unique `customTag`. It then commits an attempt boundary before calling Topstep. Successful responses are stored separately from subsequent order/trade/position facts.

If submission times out, returns a pending/unknown classification, loses acknowledgement, or the process stops after the attempt boundary, the intent becomes `ambiguous`. The executor searches documented order history for the account and time window, matches the stable `customTag` and immutable order fields, then compares trades and open positions. It never automatically repeats `Order/place` until exactly one authoritative outcome is established. Zero, multiple, inconsistent, or unavailable matches activate an account reconciliation lock and require local operator resolution.

### Reconcile provider state before and after every mutation

REST polling is the initial source of truth: account discovery, simulated contracts/history with `live: false`, order search, trade search, and open-position search. Before an entry, the executor reconciles open orders, trades since the last checkpoint, positions, local intent state, freshness, rate-limit budget, and kills. After submission it polls until a terminal or safely classified state and periodically reconciles independently of the strategy loop.

The local client implements bounded endpoint-specific token buckets below the documented provider limits, honors HTTP 429 with cooldown, and stops new mutations on authentication, authorization, clock, freshness, transport, or reconciliation failure. Provider errors never fall back to paper execution or another account.

Native cancellation and position close are mutation operations and use the same durable attempt/reconciliation boundary. A kill immediately blocks new entries; cancel-all or flatten actions require an explicit local policy and display when provider confirmation is unavailable. The user is always instructed to verify and, if necessary, intervene in TopstepX directly.

### Keep risk and strategy decisions fully local

The local policy is versioned, checksum-bound, and requires local re-consent on change. It contains exact account and instrument allowlists, strategy/configuration versions, quantity one, maximum position, maximum orders per session/day, daily loss, consecutive-loss, schedule, stale-data, clock-skew, provider-error cooldown, and kill behavior. No production financial or instrument defaults are supplied. Browser or telemetry input cannot relax the policy.

Only pure calculation modules may be shared from the current application. Local execution cannot call hosted launch-gate, scheduler, command, dry-run, or risk endpoints. Strategy inputs and decisions are persisted locally so the order is reproducible without relying on hosted state.

### Make telemetry outbound-only and non-authoritative

The local executor may POST sanitized, schema-versioned observations to a dedicated Railway ingestion endpoint using a revocable telemetry credential unrelated to Topstep. Permitted fields are coarse health, local software/configuration versions, hashed installation/account correlation identifiers, redacted order lifecycle classifications, positions, fills, P&L, risk outcomes, and timestamps. Usernames, API keys, provider tokens, full account IDs, custom tags, raw provider payloads, strategy secrets, and order-capable content are prohibited.

Telemetry responses contain only acknowledgement IDs and retry timing; the local process ignores all other response fields. There is no hosted-to-local polling, WebSocket, SSE, push, command, configuration, approval, or feature-flag channel. Telemetry failure cannot enable an order and, according to local policy, either buffers bounded events or halts new entries if observability is required.

Railway database records are projections, not execution authority. Hosted APIs expose read-only views and cannot mutate local state. Existing hosted Topstep onboarding and provider-execution routes are removed or return a permanent local-executor-required classification.

### Package and verify the local runtime independently

The executor has a dedicated entrypoint, dependency lock, local migration command, preflight, and build artifact. Production artifacts are code-signed and accompanied by a signed manifest containing version, hash, schema range, and minimum compatible policy version. The executor verifies the embedded release key and refuses mutation-capable mode for unsigned development builds. Development and CI builds can exercise mocks and Practice-like fixtures only.

Startup preflight validates interactive local execution, loopback-only control, time synchronization, OS credential availability, database integrity/migrations, single-instance lease, policy/consent/account bindings, API reachability, rate-limit configuration, and clean reconciliation. It reports only safe classifications.

### Stage provider acceptance without automating real orders

CI covers adapter contracts, policy denial, journaling, crash boundaries, ambiguity, reconciliation, rate limiting, telemetry redaction, architecture isolation, and packaging with deterministic fakes. External acceptance is manual and stage-specific:

1. Observe-only connectivity against the user's local Topstep installation.
2. Full Practice-account qualification, including restart and kill drills.
3. Revoke/rotate the key used during setup and requalify the final dedicated key.
4. Arm the exact Trading Combine locally with current consent and policy.
5. With immediate user confirmation, place and reconcile one quantity-one order during an approved window.
6. Review redacted evidence before enabling any automated Combine session.

No passing unit test, hosted deployment, or Practice result is represented as Combine-order evidence.

## Risks / Trade-offs

- **Personal-device origin cannot be perfectly attested by software** → Reject known hosted/headless environments, require interactive launch and local acceptance evidence, and document operator responsibility.
- **Account search does not classify account type** → Bind one exact ID, require explicit attestation and typed confirmation, prohibit name inference and account switching, and re-arm after every identity change.
- **A local machine can sleep, disconnect, crash, or lose power** → Journal before side effects, reconcile on restart, use native provider state where documented, fail closed on ambiguity, and require direct TopstepX verification for emergencies.
- **OS credential storage adds a platform dependency** → Support Windows Credential Manager and macOS Keychain behind one isolated interface and fail closed on unsupported systems or unavailable stores.
- **REST polling is slower than streaming** → Limit the initial strategy to non-HFT intervals, stay below documented limits, and defer realtime hubs until their recovery semantics are separately designed and tested.
- **Hosted telemetry may reveal trading information** → Minimize and hash identifiers, prohibit raw payloads/secrets, make retention explicit, and test serialized events against a strict allowlist.
- **No remote kill command is allowed** → Provide a prominent local kill, local automatic risk kills, and direct provider key revocation/manual platform intervention; hosted status can alert but cannot control.
- **Code signing and installer operations increase release complexity** → Keep mutation mode unavailable for unsigned builds and treat signing-key custody and update rollback as release gates.

## Migration Plan

1. Amend the active hosted-Combine artifacts so Railway provider execution and hosted credential custody are explicitly superseded while read-only deployment controls remain valid.
2. Add architecture tests that keep the existing hosted adapter mutation-disabled and prevent hosted imports of the local mutation client.
3. Introduce the local runtime, local database/migrations, Windows Credential Manager and macOS Keychain adapters, loopback control surface, policy/consent state machine, and mock provider client with mutation mode disabled.
4. Implement documented Topstep read-only reconciliation, durable intents/attempts, mutation methods, rate controls, and fail-closed recovery behind local-only Practice gates.
5. Add outbound-only sanitized telemetry ingestion and read-only hosted projections; remove or permanently deny hosted credential and execution surfaces.
6. Build and sign the Windows and macOS artifacts, complete clean-machine installation and rollback tests, then run local observe-only and Practice acceptance.
7. Delete/tombstone any hosted Topstep secrets, rotate the dedicated API key, configure owner-selected limits, and requalify the final local setup.
8. Conduct the separately authorized quantity-one Combine acceptance order and retain redacted evidence. Automated Combine sessions remain disabled until that review passes.

Rollback begins with the local kill, stops the executor, verifies/cancels orders and positions directly in TopstepX, revokes the API key, and preserves the local journal for reconciliation. The hosted system remains read-only throughout, so application rollback cannot silently assume execution authority.

## Open Questions

- Which Windows/macOS versions, processor architectures, and platform signing identities will be supported for the first tester?
- Which exact Practice and Combine account IDs, instruments, strategy/configuration versions, schedule, and numeric risk limits will the owner approve?
- What Practice qualification duration and minimum set of successful/failure scenarios are required before Combine arming?
- Should telemetry loss halt all new entries or permit a bounded offline interval for the first beta?
- Which native protective-order behavior and account bracket mode will be required before automated sessions, beyond the first manually confirmed acceptance order?
- What local retention and encrypted-backup policy should apply to provider identifiers and execution journals?
