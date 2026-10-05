# Local executor staged acceptance evidence

This file is a redacted evidence template, not an approval record. Never include credentials, tokens, full account IDs, custom tags, raw provider payloads, database copies, or personal information.

| Stage | Current status | Required evidence | What it does not authorize |
|---|---|---|---|
| CI deterministic fakes | PASS when linked CI run is green | Commit, test summary, architecture checks, unsigned artifact hash | Provider authentication or any real order |
| Clean signed install | PENDING EXTERNAL | Device/OS class, signed version/hash result, schema/policy compatibility, redacted preflight | Practice mutations or Combine access |
| Observe-only | PENDING EXTERNAL | Exact-account hash/suffix, connectivity/freshness classifications, `live:false`, no mutations | Practice or Combine mutations |
| Practice qualification | PENDING EXTERNAL | Each required drill classification, timestamps, reconciliation/kill outcomes, final credential generation hash | Trading Combine order |
| First Combine order | PENDING EXTERNAL USER AUTHORIZATION | Approved window, exact redacted account binding, quantity one, immediate authorization, authoritative reconciliation | Automated Combine sessions |
| Automated Combine sessions | PENDING EXTERNAL REVIEW | First-order evidence review, explicit approve/reject record, current policy/consent/preflight | Funded/live, copying, multi-account, or hosted execution |

For each completed stage, attach only a correlation ID, UTC timestamps, software/policy/configuration versions, hashed installation/account identifiers, safe classifications, test counts, and reviewer decision. Record `REJECTED` rather than weakening a gate when evidence is missing or inconsistent.
