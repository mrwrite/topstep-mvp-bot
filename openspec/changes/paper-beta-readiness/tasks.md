## Phase 1: Account Lifecycle Hardening

- [x] 1.1 [P0] Add email verification records and verified-email access gate.
  - Why it matters for beta readiness: invite-only beta users need recoverable, supportable identities before accessing paper trading.
  - Acceptance criteria: registration creates an unverified account; verification tokens are expiring and single-use; beta dashboard and paper-trading routes return `email_verification_required` until verification succeeds; resend is rate-limited.
  - Tests required: registration creates token, valid verification succeeds, expired/consumed token fails, unverified user is blocked from beta routes, resend rate limit test, cross-user token isolation test.
- [x] 1.2 [P0] Add password reset workflow with session revocation.
  - Why it matters for beta readiness: beta users need safe self-service recovery without support manually changing credentials.
  - Acceptance criteria: reset request does not reveal account existence; tokens are hashed, expiring, and single-use; successful reset updates password and revokes existing sessions.
  - Tests required: reset request response parity, valid reset, expired token, consumed token, password validation, old session revoked, no user enumeration.
- [x] 1.3 [P1] Add account recovery request workflow.
  - Why it matters for beta readiness: support needs a structured path for locked-out users without collecting sensitive data in ad hoc channels.
  - Acceptance criteria: recovery requests store sanitized message, contact email, category, status, support reference id, and user link when known; secrets are redacted.
  - Tests required: recovery request creation, anonymous request, authenticated request, redaction test, status visibility scoped to user/admin.
- [x] 1.4 [P1] Add user profile management.
  - Why it matters for beta readiness: support and onboarding need beta-safe profile data such as display name, timezone, and preferred contact email.
  - Acceptance criteria: users can view/update only their own profile fields; fields are validated; email changes require re-verification if used as login/contact identity.
  - Tests required: profile read/update, invalid field rejection, cross-user isolation, email-change re-verification.
- [x] 1.5 [P0] Add persisted session management.
  - Why it matters for beta readiness: users and support need visibility and revocation for active sessions during a beta.
  - Acceptance criteria: login creates session record; authenticated requests update last-seen metadata; users can list/revoke own sessions; revoked sessions cannot authenticate.
  - Tests required: session creation, list own sessions, revoke session, revoked token rejected, cross-user session access blocked, logout revokes current session.

## Phase 2: Legal Acceptance and Disclosure Tracking

- [ ] 2.1 [P0] Add versioned legal document records for terms, privacy, and paper-risk disclosure.
  - Why it matters for beta readiness: beta access must be tied to known document versions, not static copy without auditability.
  - Acceptance criteria: current required legal document versions are stored and retrievable; document metadata includes type, version, effective date, required flag, and content URL or markdown reference.
  - Tests required: migration/model tests, current document query, required document filtering, inactive old version handling.
- [ ] 2.2 [P0] Add user legal acceptance records.
  - Why it matters for beta readiness: the product must prove each beta user accepted required policies before paper trading.
  - Acceptance criteria: acceptance records include user id, document type/version, accepted timestamp, IP hash, user-agent summary, and metadata; records are immutable except invalidation metadata.
  - Tests required: accept required docs, duplicate acceptance idempotency, user acceptance history scoped to user, metadata redaction.
- [ ] 2.3 [P0] Gate beta product access on current legal acceptance.
  - Why it matters for beta readiness: users must accept terms, privacy, and paper-risk disclosure before using beta workflows.
  - Acceptance criteria: beta dashboard and paper-session start return stable blockers for missing terms, privacy, or paper disclosure; accepted current versions remove blockers.
  - Tests required: missing terms gate, missing privacy gate, missing disclosure gate, accepted versions pass, live trading still blocked.
- [ ] 2.4 [P1] Add re-acceptance workflow for document version changes.
  - Why it matters for beta readiness: policy changes during beta must prompt explicit user re-acceptance.
  - Acceptance criteria: when a newer required version is active, prior acceptances are insufficient; UI/API reports which document requires re-acceptance.
  - Tests required: old version accepted then new version required, blocker code returned, re-acceptance clears blocker, history retains both versions.
- [ ] 2.5 [P1] Add legal acceptance UI and audit visibility.
  - Why it matters for beta readiness: users need clear disclosures and support needs a way to inspect acceptance state.
  - Acceptance criteria: frontend shows required documents, explicit confirmations, no-profit/paper-only disclosure, acceptance timestamps, and current/missing status.
  - Tests required: frontend acceptance flow, keyboard navigation, missing acceptance state, accepted state, responsive/mobile smoke test.

## Phase 3: Invite-Only Beta Access

- [ ] 3.1 [P0] Add beta invite code model and redemption flow.
  - Why it matters for beta readiness: invite-only beta needs enforceable access control, not obscured URLs or UI-only gating.
  - Acceptance criteria: invite codes support expiry, max uses, status, issuer, optional email restriction, campaign/source, notes, and redemption records; valid redemption grants beta status.
  - Tests required: valid redemption, expired invite, disabled invite, exhausted invite, email mismatch, duplicate redemption idempotency.
- [ ] 3.2 [P0] Enforce beta access gate on beta product routes.
  - Why it matters for beta readiness: non-invited users must not access paper beta dashboards, setup, or trading workflows.
  - Acceptance criteria: users without active beta status receive `beta_access_required`; active beta users can continue through other gates; suspended beta users are blocked.
  - Tests required: unauthenticated route, authenticated no-beta user, active beta user, suspended beta user, live blocked for active beta.
- [ ] 3.3 [P1] Add waitlist support.
  - Why it matters for beta readiness: non-invited users need a controlled path to request access without creating support noise.
  - Acceptance criteria: waitlist captures email, optional name/use case/source, deduplicates entries, tracks status, and avoids revealing private invite state.
  - Tests required: join waitlist, duplicate waitlist update, invalid email, status query privacy, admin waitlist list.
- [ ] 3.4 [P1] Add admin invite and waitlist management.
  - Why it matters for beta readiness: operators need to issue invites, pause invites, approve waitlist users, and audit changes.
  - Acceptance criteria: admin-only APIs create/disable invites, inspect redemptions, approve waitlist entries, suspend beta access, and record actor/reason.
  - Tests required: admin create invite, non-admin rejected, disable invite, approve waitlist, suspend user, audit record.
- [ ] 3.5 [P1] Add user beta status API and UI surface.
  - Why it matters for beta readiness: frontend and support need stable beta status states for onboarding and troubleshooting.
  - Acceptance criteria: authenticated users can see waitlist/invited/active/suspended/exited status and next required action; UI displays status clearly.
  - Tests required: beta status API states, cross-user isolation, UI status rendering, suspended state messaging.

## Phase 4: Onboarding and Support UX

- [ ] 4.1 [P0] Add first-login onboarding flow.
  - Why it matters for beta readiness: invited users need a safe path through account verification, disclosures, beta access, and paper-only setup.
  - Acceptance criteria: first-login flow orders steps by prerequisites and blocks dashboard access until P0 steps are complete; live-disabled messaging is persistent.
  - Tests required: new user onboarding route, completed user bypass, missing verification step, missing legal step, missing beta step, mobile smoke test.
- [ ] 4.2 [P1] Add persisted onboarding checklist state.
  - Why it matters for beta readiness: activation and support require knowing where users stall.
  - Acceptance criteria: checklist tracks email verification, legal acceptance, beta status, integration creation, account/contract selection, risk review, demo loaded, and first paper session.
  - Tests required: milestone completion, idempotent updates, cross-user isolation, checklist reset/admin visibility, analytics event emission.
- [ ] 4.3 [P1] Add broker-neutral integration setup walkthrough.
  - Why it matters for beta readiness: beta users must understand selected provider capabilities and paper-only limits before setup.
  - Acceptance criteria: walkthrough explains provider capability status, credential safety, account selection, contract selection, and live-disabled status without provider expansion.
  - Tests required: walkthrough renders provider-neutral copy, roadmap provider warning, credential field accessibility, account/contract checklist state.
- [ ] 4.4 [P1] Add support contact flow.
  - Why it matters for beta readiness: beta support needs structured, sanitized issue reports tied to user context.
  - Acceptance criteria: support form records category, severity, message, optional order/session/integration ids, sanitized diagnostics, support reference id, and user notification state.
  - Tests required: create support request, validation, redaction, scoped history, admin list/update, frontend success/error states.
- [ ] 4.5 [P2] Add FAQ/help center placeholders.
  - Why it matters for beta readiness: common questions should be answered consistently before invites are sent.
  - Acceptance criteria: help pages cover paper-only status, account setup, integrations, risk controls, order states, strategy assumptions, support escalation, and no-profit guarantee.
  - Tests required: route smoke test, content presence test, responsive/accessibility smoke test, no live-available claims.

## Phase 5: Monitoring and Analytics

- [ ] 5.1 [P1] Add Sentry integration plan and configuration contract.
  - Why it matters for beta readiness: beta incidents need actionable error visibility without making external services mandatory for local development.
  - Acceptance criteria: config supports disabled/local/demo/production modes, DSN validation, environment tags, release tags, user-safe identifiers, and redaction rules.
  - Tests required: config disabled mode, invalid DSN, redaction, captured error metadata shape, no secrets in payload.
- [ ] 5.2 [P1] Add product analytics event contract.
  - Why it matters for beta readiness: beta decisions need evidence on onboarding, activation, retention, and paper engagement.
  - Acceptance criteria: analytics events have stable names, schema version, timestamp, environment, user-safe id, and redacted metadata; events can be disabled by config.
  - Tests required: event creation, schema validation, disabled mode, redaction, unknown event rejection or quarantine.
- [ ] 5.3 [P1] Add onboarding funnel metrics.
  - Why it matters for beta readiness: operators need to know where beta users fail before first paper session.
  - Acceptance criteria: metrics report registration, email verification, legal acceptance, invite activation, integration setup, account/contract selection, and first paper session conversion.
  - Tests required: fixture event funnel, date range filtering, admin authorization, empty state, privacy-safe aggregation.
- [ ] 5.4 [P2] Add activation and retention metrics.
  - Why it matters for beta readiness: beta success depends on recurring paper-trading use, not only account creation.
  - Acceptance criteria: metrics identify activated users, returning users, weekly active paper users, and cohort retention without exposing individual trading details.
  - Tests required: activation calculation, retention calculation, date windows, admin-only access, low-volume privacy guard.
- [ ] 5.5 [P2] Add paper-trading engagement metrics.
  - Why it matters for beta readiness: paper-session quality and safety signals should guide the next product phase.
  - Acceptance criteria: metrics include paper sessions, paper orders, blocked orders, kill switch activations, strategy signals, support requests, and top readiness blockers.
  - Tests required: engagement aggregation, blocked order count, kill switch count, support count, live trading unavailable assertion.

## Phase 6: Subscription Readiness

- [ ] 6.1 [P1] Define Stripe-ready billing architecture without enabling billing.
  - Why it matters for beta readiness: future paid plans should not require rewriting auth, beta access, and entitlements.
  - Acceptance criteria: design records/models reserve Stripe customer/subscription mapping fields; no checkout or payment collection is enabled in beta.
  - Tests required: beta user access without Stripe customer, billing disabled route, no external Stripe call in beta tests.
- [ ] 6.2 [P1] Add plan tier catalog.
  - Why it matters for beta readiness: product packaging should be explicit before analytics and entitlement decisions are implemented.
  - Acceptance criteria: catalog supports beta, basic paper, advanced paper, and future live-ready tiers with feature lists, status, and display metadata.
  - Tests required: plan list, inactive/future tier visibility, admin-only mutation if implemented, no billing required.
- [ ] 6.3 [P0] Add server-side entitlement model.
  - Why it matters for beta readiness: feature access must be enforceable and auditable, not client-side only.
  - Acceptance criteria: entitlement checks return allow/deny with reason codes; beta invite grants beta paper entitlements; missing/suspended beta status denies gated features.
  - Tests required: allowed beta entitlement, denied no entitlement, suspended user, cross-user isolation, route gate integration.
- [ ] 6.4 [P1] Add frontend feature gating surface.
  - Why it matters for beta readiness: users need clear explanations when features are unavailable during beta.
  - Acceptance criteria: UI consumes backend entitlement status, disables unavailable beta features, explains billing unavailable, and never presents live trading as available.
  - Tests required: entitled UI, denied UI, billing unavailable UI, live-disabled copy test, responsive smoke test.
- [ ] 6.5 [P0] Ensure entitlements cannot bypass trading safety.
  - Why it matters for beta readiness: subscription architecture must not accidentally weaken live-disabled or risk-control guarantees.
  - Acceptance criteria: any entitlement state still fails live requests through existing live-disabled gates; risk, kill switch, context, and provider capability blockers remain authoritative.
  - Tests required: entitled user live request blocked, entitled user kill switch blocked, entitled user missing context blocked, provider capability blocked.

## Phase 7: Final Beta Launch Checklist

- [ ] 7.1 [P0] Add paper-beta launch gate service/API.
  - Why it matters for beta readiness: invite waves need objective launch gates separate from live-readiness gates.
  - Acceptance criteria: launch gate reports account lifecycle, legal acceptance, invite gate, onboarding, support, monitoring, analytics, entitlements, migrations, paper safety, docs, and live-disabled status.
  - Tests required: all-pass beta gate, each P0 blocker failure, user/admin response shape, live-enabled state fails gate.
- [ ] 7.2 [P0] Block invite waves when P0 beta gates fail.
  - Why it matters for beta readiness: operators should not invite users while critical beta infrastructure is incomplete.
  - Acceptance criteria: admin invite-wave action checks beta launch gate; production P0 failures block invite generation or send actions; local/demo override is explicit and audited.
  - Tests required: invite wave blocked by gate, invite wave allowed when gates pass, override rejected in production, override audited in demo.
- [ ] 7.3 [P1] Add operational readiness documentation and runbook updates.
  - Why it matters for beta readiness: support and operators need clear procedures before real beta users arrive.
  - Acceptance criteria: docs cover account recovery, email delivery, legal re-acceptance, invite management, support incidents, analytics outages, live-disabled verification, and rollback.
  - Tests required: documentation presence smoke test, required sections test, no live-enable instructions.
- [ ] 7.4 [P1] Add support readiness checklist.
  - Why it matters for beta readiness: beta quality depends on clear ownership, response paths, and severity handling.
  - Acceptance criteria: checklist includes support owner, contact route, triage categories, response expectations, escalation criteria, and known limitations.
  - Tests required: checklist API/doc presence, missing owner fails beta gate, support route smoke test.
- [ ] 7.5 [P1] Add beta success metrics checklist and reporting.
  - Why it matters for beta readiness: the beta should have measurable success criteria before invites are sent.
  - Acceptance criteria: success metrics include activation, first paper session completion, support volume, blocker frequency, retention, paper engagement, and safety incident count.
  - Tests required: metrics report shape, empty beta metrics, populated beta metrics, admin authorization.
- [ ] 7.6 [P0] Add final safety regression proving live trading remains blocked.
  - Why it matters for beta readiness: every beta launch gate must preserve the existing no-live-execution safety boundary.
  - Acceptance criteria: tests prove beta access, legal acceptance, entitlements, invite status, and launch gate pass states still cannot enable live trading or call real provider `place_order`.
  - Tests required: live request blocked for fully eligible beta user, broker `place_order` spy not called, launch gate reports live unavailable, UI shows live-disabled messaging.
