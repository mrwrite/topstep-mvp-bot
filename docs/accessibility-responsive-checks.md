# Accessibility and Responsive Checks

These checks document the Phase 6 manual and smoke-test expectations for hosted demos.

## Viewports

- Mobile: 390px wide dashboard and integrations pages.
- Tablet: 768px wide dashboard and integrations pages.
- Desktop: 1440px wide dashboard and integrations pages.

## Critical Controls

- Login and registration inputs have visible labels and keyboard focus.
- Integration form inputs have labels, visible errors, and keyboard-reachable actions.
- Dashboard live-disabled banner is visible without scrolling on mobile.
- Readiness checklist is exposed with an accessible name.
- Emergency stop has an accessible name and remains visible on mobile.
- Start paper session is disabled while readiness blockers exist.
- Status and error banners use `role="status"` or `role="alert"` where appropriate.

## Manual Evidence

Run:

```bash
python scripts/phase6_frontend_readiness_smoke.py
cd frontend
npm run build
```

Then verify the dashboard and integrations pages at mobile, tablet, and desktop widths. No trading UI should advertise live trading as available.
