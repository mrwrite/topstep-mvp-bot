## ADDED Requirements

### Requirement: Backend-only Topstep credential validation
The authenticated Railway API SHALL accept a TopstepX platform username and API key over HTTPS, authenticate through the configured official login-key endpoint, validate provider success and token presence, request active accounts, and return only safe account-selection metadata.

#### Scenario: Successful onboarding
- **WHEN** valid credentials authenticate and active-account search succeeds
- **THEN** the API encrypts the API key before persistence, emits a redacted audit outcome, clears transient plaintext, and never returns the key or session token

#### Scenario: Failed onboarding
- **WHEN** authentication, token validation, or account search fails
- **THEN** no credential plaintext or partially usable integration is persisted and the response contains only a safe error

### Requirement: Exact account ownership, attestation, and approval
The system SHALL require the selected account ID to match a server-recorded account returned for the credential, require tester Combine attestation, and require a time-bounded administrator approval for the exact tenant, user, integration, and provider account ID.

#### Scenario: Client-supplied override
- **WHEN** a client submits another account ID, including another account returned by the same credential
- **THEN** execution authorization is denied without account-name inference or automatic switching

### Requirement: Credential replacement and revocation
Replacing or revoking a credential SHALL expire sessions, invalidate account approval and dry-run evidence, stop active runs, cancel pending work, and require new ownership discovery and approval.

#### Scenario: Dedicated key is replaced
- **WHEN** the tester replaces the Topstep API key
- **THEN** the previous ciphertext and sessions cannot authorize work and the integration returns to approval-pending state

### Requirement: Safe session lifecycle
Provider session tokens SHALL be treated as expiring secrets, retained only when required for durable worker operation, encrypted if persisted, and refreshed by safe reauthentication without logging or response exposure.

#### Scenario: Session expires during durable work
- **WHEN** a worker encounters an expired provider session
- **THEN** it stops provider submission, safely reauthenticates or fails closed, and does not reuse the expired token

### Requirement: Durable credential generation state machine
The system SHALL persist encrypted credentials, encrypted expiring sessions, discovery snapshots, attestations, and approvals by tenant, integration, and monotonically increasing credential generation; replacement SHALL validate before activation and atomically invalidate prior-generation authorization.

#### Scenario: Replacement authentication fails
- **WHEN** replacement credentials fail before the database transaction begins
- **THEN** the last valid generation remains unchanged and no new session, snapshot, attestation, or approval is activated

#### Scenario: Concurrent authorization changes
- **WHEN** approval, replacement, revocation, or deletion race
- **THEN** row locking, optimistic versions, and database uniqueness produce at most one active generation and one exact approved account

### Requirement: One authoritative execution eligibility decision
Future dry-run and provider execution paths SHALL use the single tenant service decision that evaluates integration lifecycle, current credential generation, session, discovery, attestation, exact approval, membership, cohort, kills, deletion state, and server-side live rejection.

#### Scenario: Any bound evidence is stale
- **WHEN** the account matches but any credential generation, session, snapshot, attestation, approval, cohort, or kill fact is not current
- **THEN** eligibility returns a safe typed denial and no provider order path is invoked

### Requirement: Leased and fenced durable session renewal
Topstep session validation SHALL use the database-authoritative current credential generation, a single-owner expiring renewal lease, and a monotonically increasing fence; successful validation SHALL require a new token, replace prior ciphertext, and advance session generation.

#### Scenario: Stale renewal returns after takeover
- **WHEN** an expired renewal owner returns after another worker acquired a higher fence
- **THEN** the stale token write is rejected and cannot replace the committed current session

#### Scenario: Validation explicitly rejects the token
- **WHEN** policy permits reauthentication and the integration, credential generation, and epoch remain current
- **THEN** reauthentication may use the encrypted current API key only inside the provider boundary; otherwise it fails closed

### Requirement: Security epoch binds Topstep authorization
Hosted integrations, credential generations, sessions, discovery, attestations, approvals, and credential-dependent work SHALL bind the current external monotonic security epoch.

#### Scenario: Restored database has an earlier epoch
- **WHEN** the environment epoch is higher than the database epoch
- **THEN** prior authorization is non-executable and requires operator restore reconciliation and new onboarding
