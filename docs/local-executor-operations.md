# Personal-device Topstep Combine executor operations

Status: software implementation and deterministic CI gates are available. A production signing identity, signed artifact, personal-device run, Practice qualification, and first Combine order remain external acceptance gates.

## Scope and hard boundaries

The executor supports one invited Windows or macOS user, one interactive personal computer, one dedicated API key, one exact Practice account during qualification, and one exact Trading Combine account after qualification. Express Funded, Live Funded, live brokerage, VPS/headless execution, multi-account execution, copying, and hosted order control are unsupported.

Railway accepts sanitized outbound telemetry and exposes a delayed read-only projection. It cannot configure, approve, arm, kill, cancel, close, or otherwise command the local executor. Provider state must be verified directly in TopstepX whenever local state is uncertain.

## Build, signing, and installation

1. On a controlled build machine matching the target operating system, install Python 3.12 and check out the reviewed release commit.
2. On Windows, install Inno Setup and run `./scripts/build_local_executor.ps1` to produce `Topstep-Local-Executor-Setup.exe`. On macOS, run `bash scripts/build_local_executor_macos.sh` on each supported architecture to produce `Topstep-Local-Executor-arm64.dmg` or `Topstep-Local-Executor-x86_64.dmg`. Both builds use independently pinned dependencies, disable UPX, fix Python hashing/source epoch, exclude hosted entrypoints, and report the distributable SHA-256.
3. Create a release manifest containing the exact executable hash and version, supported journal schema range, minimum policy version, issue/expiry timestamps, and `revoked: false`.
4. Sign the canonical manifest with the protected Ed25519 release private key. The corresponding public key is compiled into the executor through reviewed source control.
5. Apply the organization-approved Windows Authenticode signature or Apple Developer ID signature and notarization. Keep the release private key and platform signing identity outside the repository and build artifact.
6. Copy the installer/DMG and signed manifest to the personal device. Do not run a CI, ad-hoc-signed, or otherwise unapproved artifact for real provider mutations; it is intentionally read-only.
7. Launch interactively. Confirm loopback-only control, signed-version verification, current clock, Credential Manager support, journal integrity, single-instance lease, and the full redacted preflight.

## Credential custody and initial setup

Create a dedicated Topstep API key. Remove/tombstone any hosted Topstep credential, revoke the old key, then enter the username and dedicated key only through the local enrollment control. Credentials remain in Windows Credential Manager or the current user's macOS Keychain; session tokens are memory-only. Never put them in environment variables, command arguments, SQLite, browser storage, screenshots, logs, or support bundles.

Select accounts by exact provider ID. The operator must attest the account class and enter the displayed redacted suffix; the application does not infer type from the account name. A Practice account is required for qualification. Funded/live attestations are rejected.

## Practice qualification

1. Start in observe-only and confirm market history requests use `live: false`.
2. Review and locally activate a complete checksum-bound policy with exact account, instrument, strategy/configuration, quantity-one, loss/order/position, schedule, freshness, clock, cooldown, telemetry, and kill limits.
3. Record local consent bound to the installation, credential generation, exact account, strategy/configuration, and policy version.
4. Complete all Practice drills: accepted/rejected order lifecycle, risk denial, cancellation, restart recovery, timeout/lost-ack ambiguity, reconciliation, telemetry outage behavior, and local kill.
5. Resolve every reconciliation lock using direct TopstepX evidence. Never fabricate an acknowledgement, fill, cancellation, or position.
6. Rotate/revoke the setup API key, enroll the final dedicated key, restart, and repeat all invalidated qualification evidence.

## Trading Combine activation

Rediscover and select the exact Combine account, attest `trading_combine`, verify the redacted suffix, review current policy/consent, require clean reconciliation, and arm locally for the short configured interval. Restart, expiry, drift, or version changes disarm it.

The first Combine order is a separate gate: during an approved window, enter the immediate local authorization for the exact quantity-one intent. Reconcile it to authoritative provider state and review the redacted evidence before separately approving automated Combine sessions. CI and hosted deployment evidence never satisfy this gate.

## Emergency stop and ambiguity

Activate the local kill to stop new entries. Cancel-all and flatten are provider mutations and require explicit local confirmation; a kill by itself does not prove provider orders were cancelled or positions flattened. If the provider is unavailable or any result is uncertain, retain the journal and reconciliation lock, stop new mutations, and inspect TopstepX directly.

For a lost or compromised device, immediately revoke the dedicated Topstep API key from a trusted device, inspect/manage provider state in TopstepX, revoke the telemetry credential, and treat all unknown work as ambiguous. A replacement device requires a newly signed install and full Practice requalification.

## Backup, restore, update, and rollback

Use the local backup control while the journal is healthy. Store the backup as sensitive local data. Validation checks its SHA-256, SQLite integrity, foreign keys, and exact schema revision. Restore only to a new path; never overwrite an active journal.

An update or rollback first durably halts the executor. It is refused while ambiguous/nonterminal work exists, if the signed artifact is invalid, or if the schema/policy range is incompatible. After replacement, rerun full preflight. Success returns only to observe-only; it never restores an armed/running state.

## Credential removal, reset, and uninstall

Before destructive maintenance, halt, verify all orders/positions in TopstepX, resolve ambiguity, and create a validated backup. Credential deletion requires the exact local confirmation and still does not revoke the Topstep key. Revoke it directly in TopstepX. Reset is refused with an active reconciliation lock or nonterminal intent. Uninstall the executable only after preserving the journal and removing/revoking credentials; uninstall never means provider orders were cancelled.
