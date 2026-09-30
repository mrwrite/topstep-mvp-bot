# Security operations

## Topstep credential rotation warning

Historical versions of `app/auth.py` printed complete TopstepX authentication
responses and session tokens. The affected credentials and any derived session
tokens must be treated as potentially exposed if that code ran in an
environment whose stdout, terminal history, CI output, container logs, or log
collector was retained.

Before any future internal TopstepX use, the credential owner must:

1. Revoke active TopstepX sessions and rotate the API key through the provider.
2. Search and purge retained logs according to the incident and retention policy.
3. Record the rotation and log review in the incident register.
4. Confirm that no hosted-beta deployment enables TopstepX.

The application does not rotate or revoke external provider credentials
automatically. An operator must never record a provider revocation as successful
without provider confirmation.

## Dependency installation

- Production backend: `python -m pip install -r requirements.lock`
- Backend tests: `python -m pip install -r requirements-dev.lock`
- Frontend: `npm ci`

Production deployments must use the committed lockfiles. `DATABASE_URL` is
mandatory; production startup and Alembic never fall back to SQLite.

## Account deletion policy controls

`ACCOUNT_DELETION_GRACE_DAYS`, `ACCOUNT_RETENTION_DAYS`, and
`ACCOUNT_LEGAL_HOLD` control unresolved retention policy. Defaults are seven
days, 30 days, and no hold. Legal/compliance owners must approve production
values. Deletion immediately revokes application sessions and deletes stored
credential material. Unconfirmed external provider revocation remains visible
and retryable.
