## ADDED Requirements

### Requirement: Hosted service topology is split by responsibility
Vercel SHALL serve only the static frontend, and production Railway SHALL use separate API and private worker service roles over internal PostgreSQL and Redis connections. The API role MUST NOT run durable workers. The worker MUST use a dedicated entrypoint and database leases/fencing. PostgreSQL SHALL remain authoritative; Redis SHALL NOT own durable execution state.

#### Scenario: API restarts while worker is active
- **WHEN** an API container is restarted
- **THEN** it does not own or terminate the worker's database-authoritative job, and the separate worker resumes using lease/fence rules

### Requirement: Production deployment preflight fails closed
The hosted deployment preflight SHALL validate exact HTTPS frontend/API origins, the public-variable allowlist, private service URL shape, hosted key provider and key separation, positive security epoch, approved cohort/tester configuration, complete active database policy, live trading disabled, and provider mutations disabled. It MUST report variable names/classifications without printing values. External deployment readiness remains false until deployment evidence exists.

#### Scenario: A deployment variable contains a placeholder or unsafe origin
- **WHEN** a required secret/configuration is missing, placeholder-valued, wildcarded, localhost, or outside the exact allowlist
- **THEN** preflight returns failure without echoing the value

### Requirement: Split Vercel and Railway topology
Vercel SHALL host only the frontend, while separate Railway services SHALL host the FastAPI API, durable worker, PostgreSQL, and Redis; PostgreSQL SHALL remain authoritative and no persistent Railway volume or Redis state may own trading progress.

#### Scenario: API deployment occurs during execution
- **WHEN** a new API deployment restarts request handlers
- **THEN** the separate worker continues or safely recovers using database leases and fencing

### Requirement: Frontend secret and origin controls
The frontend SHALL compile only explicitly public configuration, SHALL never contain Topstep or application secrets, and the API SHALL accept only exact approved production and preview origins.

#### Scenario: Arbitrary preview origin calls production
- **WHEN** an unapproved Vercel preview origin makes a credentialed request
- **THEN** the Railway API rejects the origin

### Requirement: Service readiness and safe rollout
Railway services SHALL have distinct start commands, health/readiness checks, controlled migrations, internal networking, restart policy, graceful worker shutdown, heartbeat, trusted-proxy and secure-cookie settings, rate limiting, and redacted structured logging.

#### Scenario: Worker loses readiness
- **WHEN** key provider, database, Redis policy, or provider prerequisites are unavailable
- **THEN** the worker advertises failure and accepts no new provider execution

### Requirement: Secret inventory and backup operations
Operations SHALL classify every Vercel and Railway variable, use placeholders without printing values, keep user-owned Topstep keys out of deployment variables, and document PostgreSQL backup restoration and rollback.

#### Scenario: Deployment documentation is followed
- **WHEN** an operator provisions the environment
- **THEN** no command, build output, or checked-in file exposes a cryptographic or provider secret

### Requirement: Controlled acceptance
Deployment acceptance SHALL proceed through disabled services, onboarding, ownership, attestation, approval, connectivity, dry run, kills, reconciliation, restart, deletion, and revocation; a minimum-size provider order requires immediate explicit human authorization and MUST NOT run in CI.

#### Scenario: External credentials are unavailable
- **WHEN** Vercel, Railway, or Topstep credentials are not supplied
- **THEN** deployment and real-provider tasks remain open and software tests are not represented as external evidence

### Requirement: Hosted restore epoch is externally advanced
Operations SHALL configure a non-secret positive monotonic `HOSTED_SECURITY_EPOCH`, reject rollback, and increase it before a restored database is allowed to process credential-dependent work.

#### Scenario: Restore reconciliation is incomplete
- **WHEN** the environment epoch exceeds the restored database epoch
- **THEN** readiness is degraded, recovery processing remains disabled, and only the authorized idempotent reconciliation ceremony may advance the database epoch
