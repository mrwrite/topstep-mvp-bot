## Why

The app now has paper-trading safety, live-readiness blockers, operational diagnostics, and demo guardrails, but it still lacks the account lifecycle, legal acceptance, invite control, onboarding, support, analytics, and subscription architecture needed for an invite-only beta with real users.

This change prepares a strict implementation plan for a paper-trading beta without enabling live trading, expanding providers, or adding real broker execution.

## What Changes

- Add account lifecycle requirements for email verification, password reset, account recovery, profile management, and session management.
- Add versioned legal acceptance and disclosure tracking for terms, privacy policy, and paper-trading risk disclosures.
- Add invite-only beta access requirements for invite codes, waitlist support, invite tracking, admin invite management, and user beta status.
- Add onboarding and support UX requirements for first-login onboarding, integration setup guidance, paper-trading checklist, contact support, and FAQ/help placeholders.
- Add monitoring and analytics requirements for Sentry planning, product analytics planning, onboarding funnels, activation, retention, and paper-trading engagement.
- Add subscription-readiness architecture for Stripe, plan tiers, entitlements, and feature gates while keeping beta billing disabled.
- Add final paper-beta launch checklist gates covering operational readiness, support readiness, documentation readiness, and beta success metrics.
- Preserve the hard safety boundary from `consumer-ready-trading-bot-audit` and `live-readiness-blockers`: live trading remains blocked.

## Capabilities

### New Capabilities

- `account-lifecycle`: Email verification, password reset, recovery, profile management, session listing/revocation, and account state controls.
- `legal-acceptance`: Versioned terms, privacy, and paper-trading disclosure acceptance records with re-acceptance workflows.
- `beta-access`: Invite-only beta gates, invite codes, waitlist records, invite lifecycle, admin management, and user beta status.
- `onboarding-support`: First-login onboarding, integration walkthroughs, paper-trading checklists, help/contact surfaces, and FAQ placeholders.
- `beta-monitoring-analytics`: Error tracking, product analytics planning, onboarding funnel metrics, activation, retention, and paper-trading engagement metrics.
- `subscription-readiness`: Stripe architecture, plan tiers, entitlement model, feature gates, and beta no-billing policy.
- `beta-launch-readiness`: Final paper-beta launch gates, operational checks, support/documentation readiness, success metrics, and rollout controls.

### Modified Capabilities

- None. The current repository has no archived base specs under `openspec/specs/`; this change introduces beta-readiness capability specs.

## Impact

- Backend: auth routes and models, session/JWT handling, future email token services, beta invite/admin routes, legal acceptance APIs, onboarding state APIs, analytics event capture, and entitlement services.
- Frontend: login/register flows, profile/settings screens, onboarding screens, integration walkthroughs, paper beta status, legal acceptance screens, support/contact UI, and beta checklist views.
- Database/migrations: email verification tokens, password reset tokens, user sessions, legal documents/acceptances, beta invites, waitlist entries, onboarding state, analytics events, subscription plans, entitlements, and launch checklist records.
- Operations: email provider configuration, support inbox process, Sentry setup, analytics provider choice, invite administration, beta launch runbook, data retention, and privacy documentation.
- Safety: live execution remains unavailable; all beta features must preserve paper-only mode, existing risk controls, launch gates, kill switches, and provider capability restrictions.
