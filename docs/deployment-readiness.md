# Deployment Readiness Notes

This app is safe only for hosted paper-trading demos. Live broker execution remains disabled.

## Backend: Railway or Equivalent

Required production environment variables:

- `APP_ENV=production`
- `DATABASE_URL`
- `SECRET_KEY`
- `CREDENTIALS_ENCRYPTION_KEY`
- `CORS_ORIGINS=https://your-frontend.example.com`
- `ALLOW_CREATE_ALL=false`
- `RATE_LIMIT_REQUESTS_PER_MINUTE=120`

Recommended build/start sequence:

1. Install dependencies from `requirements.txt`.
2. Run `alembic upgrade head` before marking the service ready.
3. Start the API with your ASGI server, for example `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Configure health checks against `/health/ready`.

The readiness endpoint fails in production if the database cannot be reached or the Alembic head does not match the database revision.

## Frontend: Vercel or Equivalent

Required frontend environment variables:

- `VITE_API_URL=https://your-backend.example.com`

Build command:

- `npm run build`

Output directory:

- `dist`

## Secrets and Rotation

Provider credentials are encrypted with `CREDENTIALS_ENCRYPTION_KEY`. Rotate provider credentials through the integration form; do not log raw provider credential payloads. Rotating `CREDENTIALS_ENCRYPTION_KEY` requires a planned decrypt/re-encrypt migration for stored integration credentials.

Never reuse development secrets in hosted environments. Treat `SECRET_KEY` rotation as a forced-login event because existing JWTs become invalid.

## Migration Baseline

The app no longer calls `models.Base.metadata.create_all()` in production. Production startup requires `ALLOW_CREATE_ALL=false`, and readiness checks compare the database Alembic revision to the current migration head.

The current migration history should be treated as the baseline for existing demo databases. Before a consumer beta, verify a fresh database can be built from migrations alone and add a corrective baseline migration if any table creation is still missing.

## Backup and Recovery

Use managed Postgres backups for user, integration, paper order, fill, position, strategy, and audit data. Before restoring service after a database restore:

1. Restore the database from a known-good backup.
2. Run `alembic current` and `alembic upgrade head`.
3. Check `/health/ready`.
4. Confirm `/ops/status` still reports `live_trading_enabled: false`.
5. Reopen paper demo traffic only after readiness is healthy.

## Monitoring

At minimum, alert on:

- `/health/ready` returning non-200.
- repeated provider diagnostic failures.
- repeated order or strategy signal errors.
- rate-limit spikes on auth, webhook, trading, and analysis paths.

External monitoring, log shipping, and incident tooling are optional for demos but required before any consumer beta.

## Incident Response

For any provider-auth, order, webhook, or scheduler incident:

1. Keep live trading disabled; do not introduce live broker credentials as a workaround.
2. Disable affected user integrations or stop bot sessions.
3. Review structured logs by `request_id`, `user_id`, `integration_id`, `session_id`, and `order_id`.
4. Confirm `/health/ready` and `/ops/status`.
5. Restore traffic only after the paper-only path is healthy.
