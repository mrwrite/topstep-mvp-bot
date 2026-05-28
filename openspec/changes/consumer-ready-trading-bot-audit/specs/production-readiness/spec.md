## ADDED Requirements

### Requirement: Environment-specific startup validation
The backend SHALL validate required environment variables by environment and refuse production startup when required secrets, database, encryption, CORS, or provider configuration is missing.

#### Scenario: Production encryption key missing
- **WHEN** production mode starts without an explicit credentials encryption key
- **THEN** the application fails startup with a clear configuration error

### Requirement: Reproducible Railway and Vercel deployment
The project SHALL document and configure reproducible backend and frontend deployment steps, build commands, start commands, environment variables, health checks, and migration execution.

#### Scenario: Backend deploy starts
- **WHEN** the backend deploy starts on Railway or equivalent hosting
- **THEN** migrations run or are explicitly required before the service is marked ready

### Requirement: Database migration discipline
The application SHALL use Alembic migrations for production schema changes and SHALL NOT rely on runtime `create_all()` for production schema creation.

#### Scenario: Schema mismatch exists
- **WHEN** the database schema is behind the application migration head
- **THEN** readiness checks fail and trading actions are blocked

### Requirement: Production security controls
The system SHALL enforce production CORS origins, security headers, secure session handling, rate limiting, and request size limits.

#### Scenario: Unknown origin calls API
- **WHEN** a browser request originates from an unapproved production origin
- **THEN** CORS blocks the request

### Requirement: Secrets management and rotation
The system SHALL keep provider credentials and application secrets out of source control, support rotation, and avoid logging sensitive values.

#### Scenario: Credential is rotated
- **WHEN** a user rotates provider credentials
- **THEN** the system encrypts the new credentials, preserves audit history without secret values, and invalidates stale provider sessions

### Requirement: Backup and recovery
The production deployment SHALL define database backup, restore, and incident recovery procedures for user, integration, order, fill, position, audit, and bot session data.

#### Scenario: Database restore is required
- **WHEN** production data must be restored
- **THEN** the operator can follow documented restore steps and validate schema and audit integrity before reopening trading

### Requirement: Legal and risk communication
The product SHALL present paper trading, live trading risk, no guaranteed profit, user responsibility, terms, and privacy disclosures before consumer trading access.

#### Scenario: User has not accepted risk terms
- **WHEN** a user attempts to enable live trading before accepting current risk terms
- **THEN** the system blocks live trading and records no live-trading enablement
