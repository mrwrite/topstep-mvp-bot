## ADDED Requirements

### Requirement: First-login onboarding
The frontend SHALL provide a first-login onboarding flow for verified invite-only beta users.

#### Scenario: New beta user signs in
- **WHEN** a verified beta user signs in for the first time
- **THEN** the UI guides them through legal acceptance, paper-only messaging, integration setup, risk controls, and demo/paper session options

### Requirement: Paper-trading onboarding checklist
The system SHALL maintain a user-scoped onboarding checklist for paper-beta activation.

#### Scenario: Checklist milestone completes
- **WHEN** a user verifies email, accepts legal docs, creates an integration, selects account/contract, reviews risk controls, or starts a paper session
- **THEN** the corresponding onboarding milestone is recorded and reflected in the UI

### Requirement: Integration setup walkthrough
The UI SHALL provide broker-neutral walkthrough steps for creating and selecting an integration without implying live execution availability.

#### Scenario: User opens integration setup
- **WHEN** a beta user opens integration setup
- **THEN** the UI explains provider capabilities, credential safety, account selection, contract selection, and paper-only limitations

### Requirement: Support contact flow
The system SHALL provide a support contact flow that captures sanitized context for beta support.

#### Scenario: Support request submitted
- **WHEN** a beta user submits a support request
- **THEN** the system records category, severity, message, user id, optional order/session/integration ids, sanitized diagnostics, and support reference id

### Requirement: Help center placeholders
The frontend SHALL include FAQ/help placeholders for common beta topics.

#### Scenario: User opens help
- **WHEN** a beta user opens help
- **THEN** they can find paper-only status, account setup, integrations, risk controls, order states, strategy assumptions, and support escalation topics

### Requirement: Accessible onboarding and support
Critical onboarding and support screens SHALL be responsive and keyboard accessible.

#### Scenario: Mobile onboarding
- **WHEN** onboarding is rendered on mobile width
- **THEN** checklist items, actions, errors, and help links remain visible, labeled, and non-overlapping
