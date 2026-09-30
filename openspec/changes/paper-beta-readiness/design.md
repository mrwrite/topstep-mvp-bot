## Context

The completed `consumer-ready-trading-bot-audit` and `live-readiness-blockers` changes established paper-only execution, centralized trading context, persisted risk settings, kill switches, paper ledger/order lifecycle depth, reconciliation diagnostics, launch gates, migration readiness, and operational runbooks. Those changes deliberately did not solve beta-user account lifecycle, legal acceptance, invitation access, onboarding, support, analytics, or subscription architecture.

The paper beta should admit a limited set of invited users to paper-trading workflows only. It should collect the minimum operational evidence needed to understand activation, engagement, support load, and safety issues before any broader launch.

## Non-Goals

- Do not enable live trading.
- Do not call or route real broker `place_order`.
- Do not expand provider support.
- Do not implement billing or collect payment during invite-only beta.
- Do not replace legal review; this change defines product and engineering records required for review.
- Do not add a full CRM, marketing automation system, or enterprise admin console.

## Architecture

### Account Lifecycle

Add durable account lifecycle records around the existing user model:

- email verification token records with expiry, consumed timestamp, and resend limits;
- password reset token records with expiry, consumed timestamp, and rate limiting;
- recovery/contact metadata with audit events for account recovery requests;
- user profile fields that are safe for beta support, such as display name, timezone, preferred contact email, and optional trading experience level;
- session records keyed by token id or session id, device/user-agent summary, IP hash, creation time, expiry, last seen, and revoked timestamp.

Access to trading-sensitive pages should require a verified email and active beta status, while live trading remains blocked independently.

### Legal Acceptance

Legal content should be versioned as records, not only static copy. At minimum:

- terms of service version;
- privacy policy version;
- paper-trading risk disclosure version;
- accepted-by user id, document type/version, timestamp, IP hash, user-agent summary, and acceptance metadata.

The UI should require current acceptance before beta dashboard access. Future document version changes should invalidate access until re-accepted.

### Invite-Only Beta Access

Beta access should be independent of authentication:

- waitlist entries allow users to request access before an invite is issued;
- invite codes have max uses, expiry, status, issuer, campaign/source, notes, and optional email restriction;
- redeemed invites create user-scoped beta status records;
- admin APIs manage invites and waitlist status with audit logging;
- registration can accept a valid invite code or route users into waitlist mode.

This beta gate should block beta product access, not just hide UI links.

### Onboarding and Support UX

Onboarding should guide a new beta user from account creation to a safe paper session:

1. verify email;
2. accept required legal documents;
3. confirm beta access;
4. review paper-only/live-disabled messaging;
5. connect or select an integration;
6. choose account and contract;
7. review risk settings and kill switch;
8. start a paper-only session or load demo data.

Support UX should include a contact flow that captures user id, request category, severity, relevant integration/order/session ids, and sanitized diagnostic context. FAQ/help center placeholders should explain paper-only status, integrations, risk controls, orders, strategy assumptions, and support escalation.

### Monitoring and Analytics

Error tracking should be planned around Sentry or an equivalent provider but implemented behind configuration. Product analytics should be privacy-aware and should not capture secrets, raw credentials, full provider payloads, or trading account secrets.

Events should cover:

- registration started/completed;
- email verification sent/completed;
- legal acceptance completed;
- invite redeemed or waitlist joined;
- onboarding checklist milestones;
- integration created/activated;
- paper session started/stopped;
- paper order created/blocked/filled;
- kill switch activated;
- support request submitted;
- beta launch gate evaluated.

Metrics should be aggregated for onboarding funnels, activation, retention, support load, safety blockers, and paper-trading engagement.

### Subscription Readiness

Subscription readiness should define a future Stripe integration without collecting beta payments:

- plan tier catalog records;
- entitlement records derived from plan or beta access;
- feature gates checked server-side and surfaced client-side;
- Stripe customer/subscription mapping fields reserved but unused for beta;
- no-billing beta policy that grants beta entitlements through invite status only.

Feature gates must not bypass trading safety or live-disabled gates.

### Beta Launch Gates

The beta launch checklist should be separate from live-readiness gates. It should answer: "Can invited users safely use paper trading?" Required gates include:

- migrations current;
- email verification available;
- password reset available;
- legal documents current;
- invite gate enforced;
- onboarding checklist available;
- support contact available;
- error tracking configured or explicitly disabled for local;
- analytics configured or explicitly disabled for local;
- paper trading safety gates pass;
- live trading unavailable;
- operational runbook and beta success metrics documented.

## Data and Privacy

Token values should be stored hashed. IP addresses should be hashed or truncated where possible. User-agent strings should be summarized. Analytics must redact credentials, broker secrets, account secrets, API keys, and provider payloads. Legal acceptance records should retain enough metadata for audit but avoid unnecessary sensitive data.

## Testing Strategy

- Backend API tests for email verification, password reset, sessions, profile access, legal acceptance, invite redemption, waitlist, admin invite management, entitlements, launch checklist, and cross-user isolation.
- Frontend tests for registration/login, legal acceptance, onboarding, integration walkthrough, support contact, responsive behavior, and accessibility of critical controls.
- Migration tests for a fresh database and constraints on beta records.
- Analytics tests proving events are redacted and disabled when configuration is absent.
- Safety regression tests proving live requests remain blocked and no provider live execution path is introduced.

## Rollout

1. Implement account lifecycle hardening before admitting beta users.
2. Require legal acceptance and paper-risk disclosure before dashboard access.
3. Gate registration and product access behind invites or waitlist status.
4. Add onboarding/support flows and beta-specific help content.
5. Add monitoring/analytics instrumentation and privacy checks.
6. Add subscription architecture as inactive beta entitlements.
7. Run the final beta launch checklist before sending invites.
