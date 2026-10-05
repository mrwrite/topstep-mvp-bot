# Local executor credential custody

Topstep credentials belong only in Windows Credential Manager on the tester's personal device. Do not place the username, API key, telemetry credential, or provider session token in Railway, Vercel, `.env` files, command-line arguments, browser storage, SQLite, screenshots, or support messages.

## Enrollment and replacement

1. Create a dedicated Topstep API key for this executor. Do not reuse a key previously stored by a hosted deployment.
2. Enter the username and API key only through the local executor's secret enrollment control.
3. Confirm that startup reports Windows Credential Manager available. Missing OS credential-store support is a hard stop.
4. Replacing either Topstep credential invalidates Practice qualification, consent, account attestation, and Combine arming. Complete requalification before mutations are considered.
5. The telemetry credential is independently scoped and cannot authenticate to Topstep or authorize local actions.

## Rotation and deletion

Before moving from setup to final qualification, revoke the setup key in TopstepX, create a new dedicated key, replace it locally, restart, and repeat Practice qualification. Deleting local credentials removes all three Credential Manager slots but does not cancel provider orders, flatten positions, or revoke the key at Topstep. Verify provider state directly in TopstepX and revoke the API key there.

For a lost or compromised device, immediately revoke the API key in TopstepX. Hosted services cannot remotely disable, re-enable, or control the local executor.
