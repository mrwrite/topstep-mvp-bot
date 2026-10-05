## 1. Supersede Hosted Execution Authority

- [x] 1.1 Update the active hosted-Combine artifacts and operations docs to state that Railway execution and hosted Topstep credential custody are superseded by the personal-device executor.
- [x] 1.2 Keep the hosted `TopStepXAdapter`, FastAPI startup, and Railway worker mutation-disabled and return a stable `local_executor_required` classification from legacy hosted Topstep mutation surfaces.
- [x] 1.3 Add architecture tests that prohibit hosted modules, Docker artifacts, API routes, workers, and frontend code from importing or invoking the local mutation client.
- [x] 1.4 Add tests proving hosted mutation flags, production profiles, and service roles cannot make Railway order capable.

## 2. Local Executor Project Boundary

- [x] 2.1 Create a separate `local_executor` package with its own entrypoint, configuration model, dependency boundary, version metadata, and no import-time dependency on hosted database or worker modules.
- [x] 2.2 Implement local runtime detection that rejects CI, Railway, Vercel, containers, hosted service roles, noninteractive sessions, and unsupported non-Windows/non-macOS mutation-capable startup.
- [x] 2.3 Implement a single-instance local process lease and ensure secondary instances remain read-only without loading credentials.
- [x] 2.4 Add a local-only structured logging configuration with safe correlation identifiers and serialization-time secret redaction.
- [x] 2.5 Add focused startup tests for interactive, hosted, headless, CI, duplicate-instance, and unsigned-development classifications.

## 3. Local Secret Custody

- [x] 3.1 Add a secret-store interface plus Windows Credential Manager and macOS Keychain implementations for the Topstep username, dedicated API key, and independently scoped telemetry credential.
- [x] 3.2 Keep provider session tokens memory-only and implement safe session recreation and renewal without SQLite, file, log, or telemetry persistence.
- [x] 3.3 Add local credential enrollment, replacement, deletion, and key-rotation guidance without command-line or browser persistence.
- [x] 3.4 Add tests for missing credential-store support, replacement, restart, deletion, token non-persistence, and secret-bearing exception redaction.
- [x] 3.5 Add an operator migration command that tombstones/deletes any hosted Topstep credentials and records that a dedicated API-key rotation is required before local qualification.

## 4. Local Durable Journal

- [x] 4.1 Create independent local SQLAlchemy metadata, SQLite engine configuration, and a local Alembic migration chain under the user's application-data directory.
- [x] 4.2 Enable and verify SQLite foreign keys, WAL mode, busy timeout, user-only filesystem access, integrity checking, and supported schema revision at startup.
- [x] 4.3 Add local models for installation identity, lifecycle transitions, account bindings, policy versions, consent, qualification evidence, and kill state.
- [x] 4.4 Add local models for market-input identity, strategy decisions, order intents, submission attempts, acknowledgements, provider orders, trades, position snapshots, and reconciliation locks/runs.
- [x] 4.5 Add local models for sanitized audit events and a bounded outbound telemetry outbox with monotonic sequence and stable UUID constraints.
- [x] 4.6 Add migration, relationship, uniqueness, single-writer, crash-boundary, integrity-failure, backup, and schema-compatibility tests against fresh and upgraded SQLite databases.

## 5. Local Read-Only Topstep Client

- [x] 5.1 Implement `LocalTopstepClient` authentication and token validation using documented Topstep endpoints and typed, redacted provider errors.
- [x] 5.2 Implement active-account discovery and exact-ID selection without account-name classification or automatic account switching.
- [x] 5.3 Implement simulated contract search and history retrieval that always sends `live: false` and rejects any live selection.
- [x] 5.4 Implement order search, open-order search, trade search, and open-position search with normalized safe response types.
- [x] 5.5 Implement endpoint-specific local rate budgets below documented limits, durable HTTP 429 cooldown, bounded read retry, and no generic mutation retry.
- [x] 5.6 Add deterministic client contract tests for authentication, malformed responses, live rejection, account substitution, pagination/time windows, rate limits, and redaction.

## 6. Local Policy, Consent, and Activation

- [x] 6.1 Implement the fail-closed lifecycle state machine from `disabled` through Practice qualification, Combine arming/running, and `halted`, including restart invalidation.
- [x] 6.2 Implement a checksum-bound local policy requiring exact account/instrument/strategy allowlists, quantity one, position/order/loss/schedule/freshness/clock/cooldown limits, telemetry-loss behavior, and layered kills.
- [x] 6.3 Implement versioned local consent bound to installation, credential generation, exact account, strategy/configuration, and policy versions.
- [x] 6.4 Implement exact-account attestation and typed redacted-suffix confirmation for Practice and Trading Combine accounts while rejecting funded/live attestations.
- [x] 6.5 Implement Practice qualification evidence for order lifecycle, risk rejection, cancellation, restart, ambiguity, reconciliation, and kill drills with invalidation on relevant changes.
- [x] 6.6 Implement short-lived Combine arming and individually authorized first-order acceptance; restart, expiry, state drift, or version changes must disarm.
- [x] 6.7 Add lifecycle, policy, consent, attestation, qualification, kill, expiry, quantity, account-switching, funded/live rejection, and first-order authorization tests.

## 7. Local Strategy and Risk Boundary

- [x] 7.1 Extract or wrap only pure strategy and indicator calculations needed by the local executor without importing hosted routes, schedulers, commands, launch gates, or database services.
- [x] 7.2 Persist versioned local market inputs, strategy decisions, proposed intents, and risk classifications so each decision is reproducible.
- [x] 7.3 Implement local pre-trade checks for exact account, instrument, strategy/configuration, quantity, position, orders/session/day, daily loss, consecutive loss, schedule, stale data, clock skew, cooldown, reconciliation, telemetry policy, and kills.
- [x] 7.4 Add tests proving hosted signals/configuration cannot cause local decisions and proving every missing, stale, relaxed, or inconsistent risk input denies before intent submission.

## 8. Mutation Client and Intent Pipeline

- [x] 8.1 Implement documented local-only order placement with supported order types, explicit quantity one, stable unique `customTag`, and typed provider error classifications.
- [x] 8.2 Implement local-only order cancellation and modification through the same durable safety boundary.
- [x] 8.3 Implement local-only full and partial position close through the same durable safety boundary.
- [x] 8.4 Implement the transaction sequence that commits immutable intent, commits the submission-attempt boundary, performs exactly one network call, and separately records acknowledgement.
- [x] 8.5 Classify timeout, transport loss, pending/unknown response, malformed response, lost acknowledgement, and post-attempt crash as ambiguous without automatic resubmission.
- [x] 8.6 Require immediate provider-state reconciliation before every mutation and block simulator fallback, remote fallback, account switching, and generic retry middleware.
- [x] 8.7 Add deterministic mutation tests for accepted, rejected, pending, rate-limited, ambiguous, interrupted, duplicate-tag, cancellation, modification, close, kill, and stale-authorization cases.

## 9. Reconciliation and Restart Recovery

- [x] 9.1 Implement reconciliation matching by exact account, stable `customTag`, immutable intent fields, time window, provider order, trades, and open positions.
- [x] 9.2 Resolve exactly one authoritative match without resubmission and retain an account reconciliation lock for zero, multiple, stale, unavailable, or inconsistent outcomes.
- [x] 9.3 Implement startup recovery that distinguishes unattempted intents from ambiguous attempts and reconciles all nonterminal work before arming.
- [x] 9.4 Implement periodic reconciliation independent of the strategy loop and durable checkpoints for order, trade, position, and local-ledger projections.
- [x] 9.5 Implement explicit local operator resolution that records evidence but cannot fabricate provider acknowledgement, fill, cancellation, or position state.
- [x] 9.6 Add failure-injection tests at every intent/attempt/response/commit boundary plus restart, sleep, clock change, database lock, provider outage, and reconciliation drift cases.

## 10. Local Control Surface and Preflight

- [x] 10.1 Add a loopback-only local control surface that serves pinned local assets, validates Host/Origin, and requires a per-launch anti-CSRF secret.
- [x] 10.2 Add local interfaces for credential enrollment, account discovery, attestation, policy review, consent, Practice qualification, Combine arming, health, kill, reconciliation, backup, and uninstall guidance.
- [x] 10.3 Ensure the local UI never repopulates secrets and requires immediate confirmation for first Combine order, cancel-all, flatten, credential deletion, and destructive reset.
- [x] 10.4 Implement redacted startup preflight covering runtime origin, signed version, clock, credential store, database, lease, policy, consent, exact account, rates, provider connectivity, telemetry policy, and reconciliation.
- [x] 10.5 Add loopback binding, Host/Origin, CSRF, secret-clearing, confirmation, preflight, and prohibited-remote-control tests.

## 11. Outbound-Only Telemetry

- [x] 11.1 Define a versioned telemetry allowlist for coarse health, versions, timestamps, hashed installation/account correlation, lifecycle classifications, sanitized fills/positions/P&L, risk outcomes, and audits.
- [x] 11.2 Implement serialization-time rejection of credentials, tokens, full account IDs, custom tags, raw provider payloads, database content, strategy secrets, and order-capable fields.
- [x] 11.3 Implement local outbound HTTPS delivery with a scoped device credential, bounded outbox, acknowledgement-only response parsing, and policy-controlled outage behavior.
- [x] 11.4 Add a Railway ingestion endpoint and database projection that are tenant/installation scoped, append-only, non-authoritative, and inaccessible with Topstep or administrative credentials.
- [x] 11.5 Add read-only hosted dashboard projections with delayed/stale labeling, last-device-event status, and no order, policy, approval, kill, cancel, or close controls.
- [x] 11.6 Add tests proving there is no hosted-to-local polling, push, WebSocket, SSE, callback, configuration, command, or feature-flag channel and that unexpected response fields are ignored and audited.
- [x] 11.7 Add telemetry tenant-isolation, credential-scope, retention, redaction, backpressure, replay, drift, and offline-budget tests.

## 12. Packaging, Signing, Update, and Recovery

- [x] 12.1 Add a dedicated locked dependency set plus reproducible Windows installer and macOS app/DMG builds for the local executor without hosted worker or server-only mutation entrypoints.
- [x] 12.2 Implement signed release-manifest verification for executable hash, version, schema range, minimum policy version, expiry/revocation, and embedded release public key.
- [x] 12.3 Ensure unsigned development and CI builds can use only deterministic fake-provider or read-only modes and cannot enable real provider mutations.
- [x] 12.4 Implement safe update and rollback checks that halt new entries, preserve ambiguous work, validate schema compatibility, rerun preflight, and never restore a more permissive lifecycle state.
- [x] 12.5 Implement explicit local journal backup/restore, uninstall, reset, credential removal, and API-key revocation workflows that never imply provider orders were cancelled.
- [x] 12.6 Add clean-machine install, signature tamper, incompatible schema, update interruption, rollback, backup integrity, uninstall, and lost-device incident tests.

## 13. Automated Verification and Documentation

- [x] 13.1 Add architecture checks for local/hosted dependency separation, prohibited remote order channels, mutation-call containment, and absence of secrets in builds and fixtures.
- [x] 13.2 Run focused local executor unit, integration, crash-boundary, reconciliation, telemetry, UI security, migration, and packaging suites with deterministic provider fakes.
- [ ] 13.3 Run the full backend and frontend regression suites, explicit PostgreSQL hosted-telemetry tests, dependency checks/audits, warning-budget checks, compile/import checks, and OpenSpec strict validation.
- [x] 13.4 Document local installation, credential custody, Practice qualification, Combine activation, emergency stop, direct TopstepX verification, key revocation, backup, update, rollback, and uninstall procedures.
- [x] 13.5 Create a redacted staged evidence report distinguishing CI, clean-install, observe-only, Practice, first Combine order, and automated Combine-session approval.

## 14. External Personal-Device Acceptance

- [ ] 14.1 Select and approve the Windows or macOS version/architecture, platform and release signing identity/custody, exact personal device, Practice and Combine accounts, instruments, strategy/configuration versions, schedule, numeric risk limits, telemetry outage policy, retention, and protective-order behavior.
- [ ] 14.2 Install the signed executor on the personal device, verify no hosted Topstep credential remains, rotate to a dedicated local API key, and pass redacted startup preflight.
- [ ] 14.3 Complete observe-only connectivity and every required Practice-account order, risk, restart, ambiguity, cancellation, reconciliation, telemetry, and kill drill.
- [ ] 14.4 Revoke/rotate the setup key, requalify the final credential and configuration, and arm the exact Trading Combine through local attestation, consent, suffix confirmation, and clean reconciliation.
- [ ] 14.5 With immediate explicit user authorization, submit and reconcile one quantity-one Trading Combine order locally; record only redacted evidence and do not automate this task in CI.
- [ ] 14.6 Review first-order evidence and explicitly approve or reject automated Combine sessions; Express Funded, Live Funded, live brokerage, multi-account, trade-copying, and remote execution remain NO-GO.
