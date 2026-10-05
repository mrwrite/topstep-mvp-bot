> **Superseded execution target (2026-10-02):** `add-local-topstep-combine-executor` replaces Railway provider execution and hosted Topstep credential custody. This change remains historical evidence for hosted read-only controls, migrations, deletion, and telemetry only. Its hosted order-execution requirements MUST NOT be implemented.

## Why

The next evidence target is a reversible, one-tester Topstep Trading Combine beta on Vercel and Railway rather than immediate Raspberry Pi production. The hosted slice must permit meaningful simulated-provider testing without weakening tenant boundaries, durable execution, credential protection, or the server-side prohibition on live trading.

## What Changes

- Add a narrowly scoped Railway-secret envelope provider for the hosted-beta deployment mode, with versioned keys, authenticated wrapping, rotation, and explicit risk acceptance.
- Add backend-only TopstepX credential validation, encrypted persistence, safe account discovery, replacement, revocation, and deletion.
- Add exact-account ownership, tester attestation, administrator approval, expiry, emergency revocation, and one-account cohort enforcement without name-based classification.
- Add a fail-closed Trading Combine execution boundary, conservative server-owned risk policy, read-only dry run, provider reconciliation, and durable-worker-only execution.
- Add Vercel frontend and separate Railway API/worker/PostgreSQL/Redis deployment contracts, secret inventory, rollback, and acceptance procedures.
- Reclassify physical TPM evidence as deferred and non-blocking only for this one-user hosted Trading Combine beta; retain it for self-hosted and future live/live-credential profiles.
- Split release governance into internal software, internal simulation, Trading Combine, Express Funded, and live-funded/live-brokerage stages.
- Preserve the prohibition on AWS, Express Funded Accounts, Live Funded Accounts, and live brokerage execution.

## Capabilities

### New Capabilities

- `hosted-beta-key-management`: Explicit Railway-secret envelope provider, key-version rotation, startup enforcement, and hosted trust limitations.
- `topstep-combine-onboarding`: Backend credential validation, safe account discovery, attestation, exact-account approval, replacement, and deletion.
- `topstep-combine-execution`: Durable-worker-only simulated provider execution, reconciliation, dry run, conservative risk controls, and kill behavior.
- `hosted-beta-deployment`: Vercel/Railway topology, secret inventory, origin policy, service readiness, rollback, and controlled tester acceptance.

### Modified Capabilities

- `managed-secret-protection`: Permit only the explicitly named hosted-beta provider for the scoped Railway mode while retaining TPM requirements elsewhere.
- `tenant-isolation`: Bind credentials, discovered accounts, approvals, provider commands, and deletion to the owning tenant and exact integration.
- `durable-bot-execution`: Require provider-side execution to remain solely in the fenced Railway worker.
- `simulation-execution-recovery`: Require provider reconciliation before continuation and prohibit ambiguous automatic resubmission or fallback.
- `release-governance`: Add a distinct conditional Trading Combine beta stage without enabling funded or live stages.
- `beta-operations`: Add hosted topology, secret, backup, incident, rollback, and controlled acceptance requirements.
- `account-deletion-backup-handling`: Prevent any worker, command, recovery, or outbox path from using deleted Topstep credentials.

## Impact

Affected areas include FastAPI configuration and routes, encryption providers, TopstepX/ProjectX integration, durable worker and recovery flows, risk controls, database schema and migrations, React onboarding/status interfaces, CI architecture checks, Vercel/Railway deployment descriptors, operational documentation, and parent/TPM OpenSpec evidence. External deployment and real-provider acceptance remain open unless credentials and explicit order authorization are supplied.
