# Hosted Topstep Trading Combine beta operations

Status: software preparation only. No Vercel, Railway, Topstep credential, dry-run, or order evidence has been collected.

## Scope and accepted risk

This profile permits one invited tester, one tenant, one TopstepX integration, and one exact administratively approved Trading Combine account. It excludes Express Funded, Live Funded, live brokerage, and account switching. A Combine is simulated execution but provider actions can affect evaluation status, rule compliance, and subscription value. The tester must consent before automation is enabled.

`railway-secret-envelope-v1` stores its versioned 256-bit wrapping keys in Railway service variables. Railway project administrators and a compromised authorized runtime can access those variables. This is an owner-accepted limitation only for this narrow beta; it is not TPM-equivalent. The physical TPM profile remains future self-hosted/live-credential work.

## Topology

- Vercel: frontend assets only. It receives only the public Railway API URL.
- Railway API: public FastAPI HTTPS endpoint; it validates requests and creates durable commands but never owns execution.
- Railway worker: private durable command/evaluation/outbox worker with leases and fencing; no public route.
- Railway PostgreSQL: authoritative commands, approvals, leases, checkpoints, outbox, risk, deletion, and audit state.
- Railway Redis: non-authoritative rate-limit/cache/coordination state only.
- TopstepX: external simulated provider. Contract/history selection always sends `live: false`.

## Variable inventory

Values below are names and placeholders only. Never paste real values into source, tickets, logs, shell history, or evidence.

| Service | Variable | Classification | Required rule |
|---|---|---|---|
| Vercel | `VITE_API_URL` | Public build configuration | Exact Railway API HTTPS origin; no credentials |
| Railway API/worker | `APP_ENV=production` | Deployment control | Production validation enabled |
| Railway API/worker | `DEPLOYMENT_PROFILE=hosted_topstep_combine_beta` | Deployment control | Required for hosted provider |
| Railway API/worker | `DATABASE_URL` | Database connection | Railway private PostgreSQL URL |
| Railway API/worker | `REDIS_URL` | Redis connection | Railway private Redis URL; non-authoritative |
| Railway API | `CORS_ORIGINS` | Private application configuration | Exact Vercel production and explicitly approved preview origins; never `*` |
| Railway API/worker | `SECRET_KEY` | Cryptographic secret | Session/application auth only; distinct from every other key |
| Railway API/worker | `KEY_MANAGEMENT_PROVIDER=railway-secret-envelope-v1` | Provider configuration | No alias or implicit default |
| Railway API/worker | `KEY_MANAGEMENT_KEY_ID` | Provider configuration | Stable non-secret identity |
| Railway API/worker | `KEY_MANAGEMENT_ACTIVE_VERSION` | Provider configuration | Active write version |
| Railway API/worker | `RAILWAY_ENVELOPE_KEY_VERSIONS_JSON` | Cryptographic secret | JSON of version to base64url 32-byte keys; active plus approved prior only |
| Railway API/worker | `TOPSTEP_CREDENTIAL_FINGERPRINT_KEY` | Cryptographic secret | Independent base64url key of at least 32 bytes; keyed duplicate signal only |
| Railway API/worker | `LEGACY_FERNET_MODE=envelope-only` | Deployment control | Hosted beta does not silently fall back |
| Railway API/worker | `TOPSTEP_BASE_URL=https://api.topstepx.com` | Provider configuration | Exact official REST endpoint |
| Railway API/worker | `LIVE_TRADING_ENABLED=false` | Deployment control | Must remain false |
| Railway API/worker | `HOSTED_PROVIDER_EXECUTION_ENABLED=false` | Deployment control | Remains false until acceptance gates pass |
| Railway API/worker | `HOSTED_WORKER_PROCESSING_ENABLED=false` | Deployment control | Must remain false during restore reconciliation |
| Railway API/worker | `HOSTED_SECURITY_EPOCH` | Non-secret deployment control | Positive monotonic integer; increase before any restored database is processed; rollback is rejected |
| Railway API/worker | `TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES=120` | Private application configuration | Server-owned conservative renewal window |
| Railway API/worker | `TOPSTEP_SESSION_RENEWAL_LEASE_SECONDS=60` | Private application configuration | Durable single-flight lease; 15-600 seconds |
| Railway API/worker | `TOPSTEP_BETA_COHORT_ID` | Cohort/risk policy | Exact owner-approved initial cohort |
| Railway API/worker | `TOPSTEP_APPROVED_TESTER_USER_ID` | Cohort/risk policy | Exact single tester database identity |
| Railway API/worker | `TOPSTEP_BETA_COHORT_ENABLED=false` | Cohort/risk policy | Enable only after software, deployment, consent, dry-run, and approval gates |
| Railway API/worker | account/instrument/strategy/schedule/numeric risk variables | Cohort/risk policy | Owner-approved conservative limits; no browser relaxation |

The tester's Topstep username and API key are user-owned credential data, not deployment variables. They enter through authenticated HTTPS onboarding and are persisted only as tenant-bound ciphertext. Session tokens are secrets and never appear in responses, logs, traces, analytics, or audits.

## Safe key creation and rotation

Generate each 32-byte wrapping key in a trusted operator environment and enter it directly in the Railway dashboard's sealed variable editor. Do not pass values on a command line or capture screenshots/output. Add the new version alongside the prior version, set the new active version, deploy with provider execution disabled, pass readiness, rewrap idempotently, reconcile every record, and retain the prior version until inventory, backup/restore, rollback, and approval evidence pass. Removing a still-required prior version makes affected records deliberately unavailable.

## Deployment and rollback

1. Provision PostgreSQL and Redis with private networking and backups; restore a backup into an isolated target and verify migration/head before acceptance.
2. Run Alembic as a controlled release step. Do not use `create_all`.
3. Deploy API with provider execution disabled; verify key-provider/database readiness, exact CORS, trusted proxy, secure cookies, rate limits, redacted logs, and health.
4. Deploy the separate worker with provider execution disabled; verify heartbeat, graceful stop, lease expiry/handoff, fencing, and reconciliation after restart.
5. Deploy Vercel and scan the bundle/responses for secrets. Reject arbitrary preview origins.
6. Complete onboarding, ownership snapshot, attestation, exact approval, consent, connectivity, dry run, and kill drills.
7. A real minimum-size Combine order requires immediate explicit owner confirmation and is never CI automation.

Rollback starts by disabling provider execution and activating global/tenant/account/run kills. Revoke approval, stop new claims, cancel pending commands, reconcile every ambiguous attempt, then roll back API/worker/frontend while retaining the compatible database. Database downgrade or key removal requires exact dependency inventory, successful restore evidence, approval, and documented loss/rollback implications.

## Disconnect, restore, and incident response

Disconnect must first commit an authoritative tombstone, expire sessions, revoke approval, activate kills, and cancel credential-dependent commands/outbox work. Ciphertext deletion follows that boundary. The UI then directs the tester to revoke the dedicated key in TopstepX Settings > API; it never redisplays the key.

### Restore security-epoch ceremony

A database backup cannot prove that it includes the latest deletion or revocation. `HOSTED_SECURITY_EPOCH` is therefore an external, non-secret monotonic restore boundary. Normal writes bind integrations, credential generations, sessions, discovery, attestations, approvals, commands, runs, and outbox work to the current epoch. A lower environment value is a rejected rollback. A higher value makes readiness fail and keeps worker recovery stopped; the application does not rewrite restored records into the new epoch.

1. Disable provider execution and worker processing and verify both controls are false.
2. Increment `HOSTED_SECURITY_EPOCH` in the Railway API and worker environments before restored services are allowed to process work. Never reuse or decrement an epoch.
3. Restore PostgreSQL while API/worker processing remains disabled. Confirm `/health/ready` reports `reconciliation_required`.
4. Run `python scripts/reconcile_hosted_restore.py --operator-id <ADMIN_ID> --target-tenant-id <TESTER_ID> --case <CASE> --correlation-id <CORRELATION>` from an authorized Railway administrative job. Arguments are non-secret identifiers; do not include account IDs or credentials.
5. The transaction suspends every restored Topstep integration, revokes approvals and attestations, erases encrypted sessions and credentials, kills runs, cancels commands, terminally suppresses outbox work, and records privacy-preserving evidence. It never contacts Topstep.
6. If it fails, keep both execution controls disabled and retry with the same correlation ID after correction. The database epoch advances only in the final commit. An acknowledgement failure after that commit is idempotently recognized.
7. Verify the database epoch equals the environment epoch and readiness returns `ready`. Keep provider execution disabled.
8. Require the tester to create/reconnect a dedicated key, repeat account discovery and Combine attestation, and obtain a new exact approval. Prior credentials and approvals are never revived.

This procedure defaults to revoking all restored Topstep access. It does not automatically detect that Railway performed a restore; the operator must increment the external epoch before restored services start. A backup predating deletion cannot execute when this ceremony is followed.

For provider authentication failure, suspected key disclosure, Railway root-key exposure, or tester offboarding: disable execution, kill runs, revoke exact approval, tombstone/delete local credentials, direct Topstep revocation, rotate affected hosted keys, inventory all dependent envelopes/backups, reconcile provider state, retain only redacted audit outcomes, and require owner approval before re-enablement.

## Controlled acceptance evidence

Evidence must redact username, API key, session token, account ID, personal information, and root-key material. Record commands, revision, time, service, status, counts, warning/skips, and correlation IDs. Local mocks do not close Vercel, Railway, provider sandbox, backup restore, deletion/revocation, or real-order tasks.
