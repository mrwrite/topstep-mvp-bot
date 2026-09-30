## ADDED Requirements

### Requirement: Official least-privilege connection flow
The system SHALL connect only through an official provider API and SHALL prefer delegated OAuth authorization with PKCE and minimum scopes. It MUST NOT use browser automation, scrape credentials, store broker passwords when delegated authorization exists, or advertise an unapproved provider.

#### Scenario: Provider lacks an authorized API
- **WHEN** a user selects a platform without an official, contractually permitted integration path
- **THEN** the platform is shown as unsupported with a reason and no credentials are requested

### Requirement: Verified account and environment
The server SHALL discover accounts through the provider, record the provider-verified paper, demo, or live environment, and require explicit account selection. Client-supplied environment labels MUST NOT override provider evidence.

#### Scenario: Account environment disagrees with configuration
- **WHEN** provider discovery identifies a live account for a paper configuration
- **THEN** connection validation fails closed, no bot run starts, and an environment-mismatch audit event is recorded

### Requirement: Credential lifecycle
Broker grants and secrets SHALL be encrypted, non-redisplayable, rotatable, health-checked, revocable, and deleted on disconnect subject to audit retention. Logs, analytics, support records, and errors MUST redact them.

#### Scenario: User disconnects provider
- **WHEN** a user confirms disconnect for a broker connection
- **THEN** runs are stopped, provider revocation is attempted, local tokens and keys become unusable, pending state is reconciled, and the result is audited
