# Launch Readiness Checklist

## Demo-Ready

- [x] Live trading disabled.
- [x] Paper-only demo package can be seeded and reset per user.
- [x] Dashboard shows paper-only and live-disabled messaging.
- [x] Health/readiness and operational status endpoints exist.
- [x] Investor walkthrough and smoke-test guidance exist.

## Paper-Ready

- [ ] Central `TradingContextService` resolves account, contract, mode, integration, and market-data scope everywhere.
- [ ] Risk settings schema covers max daily loss, trade size, contracts, open positions, and kill switch state.
- [ ] User/account-scoped kill switch records exist.
- [ ] Responsive and accessibility tests cover dashboard, integrations, auth, and stop controls.
- [ ] Paper execution includes richer simulation assumptions for equity, PnL, slippage, commissions, and contract metadata.

## Live-Ready

- [ ] Live trading acknowledgement records and legal review are complete.
- [ ] Stop/limit/stop-limit orders and provider capability checks are implemented.
- [ ] Provider order status reconciliation handles accepted, rejected, partial fill, fill, cancel, timeout, and unknown states.
- [ ] Safe retry behavior reconciles unknown provider state before resubmission.
- [ ] Live positions reconcile against provider state.
- [ ] Terms, privacy policy, support, incident escalation, and regulatory review are complete.

Live trading must remain unavailable until every live-ready item is complete and verified.
