## ADDED Requirements

### Requirement: Error tracking plan
The project SHALL support a Sentry or equivalent error tracking integration plan with environment-based enablement and secret redaction.

#### Scenario: Error tracking disabled
- **WHEN** error tracking DSN/config is absent
- **THEN** the application continues to run and records that remote error tracking is disabled

### Requirement: Product analytics plan
The project SHALL define privacy-aware product analytics instrumentation for beta workflows.

#### Scenario: Analytics event emitted
- **WHEN** a beta workflow event is captured
- **THEN** the event includes a user-safe identifier, event name, timestamp, environment, and redacted metadata only

### Requirement: Onboarding funnel metrics
The system SHALL track onboarding funnel events from registration through first paper session.

#### Scenario: Funnel report requested
- **WHEN** an admin requests onboarding funnel metrics
- **THEN** the report shows counts and conversion rates for registration, email verification, legal acceptance, invite activation, integration setup, and first paper session

### Requirement: Activation and retention metrics
The system SHALL define activation and retention metrics for beta users.

#### Scenario: Beta metrics generated
- **WHEN** metrics are generated for a date range
- **THEN** the output includes activated users, returning users, active paper users, and retention cohorts where data is available

### Requirement: Paper trading engagement metrics
The system SHALL track paper-session and paper-order engagement without implying profitability.

#### Scenario: Engagement metrics requested
- **WHEN** beta engagement metrics are requested
- **THEN** the output includes paper sessions, paper orders, blocked orders, kill switch activations, strategy signals, and support contacts

### Requirement: Analytics redaction
Analytics and error events SHALL NOT include credentials, raw secrets, full provider payloads, or live account secrets.

#### Scenario: Event metadata contains secret-like keys
- **WHEN** analytics receives metadata containing credential, token, secret, password, or key fields
- **THEN** those values are redacted before persistence or external transmission
