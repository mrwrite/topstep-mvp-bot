# Durable simulation process-restart drill

- Result: **PASS**
- Lease takeover fence advanced: `True`
- Crash process exit: `91`
- Economic counts after recovery: `{"evaluations": 2, "fills": 2, "ledger_entries": 2, "orders": 2, "risk_trade_count": 2}`
- Killed run remained killed: `True`
- Killed run effects: `{"evaluations": 0, "fills": 0, "ledger_entries": 0, "orders": 0, "risk_trade_count": 0}`

This drill uses local simulation only. It does not contact a broker or demonstrate future returns.
