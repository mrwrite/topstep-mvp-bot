# Investor Demo Package

This repository is demo-ready for paper-only walkthroughs. It is not live-trading ready.

## Demo Guardrails

- Live broker execution remains disabled by backend safety checks.
- Demo data is marked per user and uses `DEMO-PAPER-001`.
- Demo credentials are fake and point at `https://demo.invalid`.
- Demo orders are local paper orders with idempotency keys prefixed by `demo:`.
- Demo reset removes only the current user's demo-marked records.

## Walkthrough

1. Start the backend and frontend.
2. Register or log in with a demo user.
3. Open the dashboard.
4. Select `Load demo` in the Investor demo panel.
5. Review the mode banner: it must say paper trading only and live disabled.
6. Review paper order history, paper positions, strategy metrics, provider status, and readiness blockers.
7. Use `Reset` when the walkthrough is complete.

## Talking Points

- The app can demonstrate broker setup, account/contract context, paper order lifecycle, paper positions, strategy metrics, and operational health.
- The app must not be presented as capable of live trading.
- Paper/backtest results do not predict or guarantee live results.
- Remaining blockers are tracked in `docs/launch-readiness-checklist.md`.

## Smoke Test

Run the local smoke script after backend dependencies are installed:

```bash
python scripts/demo_smoke.py
```

The script exercises registration/login, demo seeding, paper order visibility, status checks, and demo reset through the FastAPI app without connecting to a real broker.
