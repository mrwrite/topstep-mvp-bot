## ADDED Requirements

### Requirement: Stripe readiness architecture
The project SHALL define Stripe-ready customer, subscription, and checkout architecture without enabling billing during invite-only beta.

#### Scenario: Beta user has no Stripe customer
- **WHEN** a beta user accesses beta features
- **THEN** access is determined by beta entitlement, not by Stripe payment state

### Requirement: Plan tiers
The system SHALL model plan tiers for future billing.

#### Scenario: Plans requested
- **WHEN** plan tiers are requested
- **THEN** the response lists beta, basic paper, advanced paper, and future live-ready tiers as configuration records without requiring payment

### Requirement: Entitlement model
The system SHALL evaluate feature access through a server-side entitlement model.

#### Scenario: Feature gate evaluated
- **WHEN** a user attempts to access a gated beta feature
- **THEN** the backend checks user entitlement and returns allow/deny with a stable reason code

### Requirement: Feature gating model
The frontend SHALL use backend entitlement state to hide or disable unavailable beta features.

#### Scenario: User lacks entitlement
- **WHEN** a user lacks an entitlement for a feature
- **THEN** the UI explains the unavailable state and does not rely only on client-side hiding

### Requirement: No beta billing
The system SHALL NOT collect payment or require billing details for invite-only paper beta access.

#### Scenario: Billing route requested during beta
- **WHEN** a beta user attempts to open billing or checkout
- **THEN** the system shows billing unavailable for beta and does not start checkout

### Requirement: Trading safety overrides entitlements
Entitlements SHALL NOT enable live trading, bypass risk controls, bypass launch gates, or bypass provider capability restrictions.

#### Scenario: Entitled user requests live trading
- **WHEN** any user with any entitlement requests live trading while live is disabled
- **THEN** the system blocks live trading with the existing live-disabled readiness reason
