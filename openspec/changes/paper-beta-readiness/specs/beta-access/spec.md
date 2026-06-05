## ADDED Requirements

### Requirement: Invite-only beta gate
The system SHALL require an active beta invite redemption or approved beta status before paper-beta access is granted.

#### Scenario: User lacks beta access
- **WHEN** an authenticated user without approved beta status opens beta product routes
- **THEN** the system blocks access with `beta_access_required`

### Requirement: Beta invite codes
The system SHALL support beta invite codes with expiry, max uses, status, issuer, optional email restriction, and redemption tracking.

#### Scenario: Invite code redeemed
- **WHEN** a user redeems a valid invite code
- **THEN** the system records redemption, increments usage, and grants beta status to the user

#### Scenario: Invite code exhausted
- **WHEN** a user submits an expired, disabled, email-mismatched, or exhausted invite code
- **THEN** the system rejects redemption without granting beta access

### Requirement: Beta waitlist
The system SHALL support a waitlist for users without invite codes.

#### Scenario: User joins waitlist
- **WHEN** a prospective user submits waitlist information
- **THEN** the system stores the request, deduplicates by email, and returns a non-sensitive status

### Requirement: Admin invite management
The system SHALL provide admin-only invite and waitlist management APIs.

#### Scenario: Non-admin manages invites
- **WHEN** a non-admin attempts to create, disable, or inspect invite codes
- **THEN** the system rejects the request

### Requirement: User beta status
The system SHALL expose user beta status to the frontend and backend gates.

#### Scenario: Beta status requested
- **WHEN** an authenticated user requests beta status
- **THEN** the response indicates waitlist, invited, active, suspended, or exited state
