# Hosted Topstep Combine deployment template

This is a deployment template, not deployment evidence. No Vercel or Railway service has been
created by this change. Provider orders remain disabled.

## Topology

- Vercel: frontend static build only (`frontend/` as the project root); set public `VITE_API_URL`
  to the exact Railway API HTTPS URL. No Topstep, database, Redis, or encryption secret belongs in
  Vercel.
- Railway API: root Dockerfile, `SERVICE_ROLE=api`, `APP_ENV=production`, `DEPLOYMENT_PROFILE=hosted_topstep_combine_beta`.
- Railway worker: same immutable image, start command `python -m app.worker_entrypoint`,
  `SERVICE_ROLE=worker`; do not expose a public domain.
- Railway PostgreSQL and Redis: internal Railway references only. PostgreSQL is authoritative;
  Redis is only rate-limit/coordination infrastructure.
- Controlled release step: `alembic upgrade head`, followed by readiness verification before API
  and worker traffic is enabled.

The API process does not start the worker when `SERVICE_ROLE=api`. The worker entrypoint requires
`SERVICE_ROLE=worker`. Development retains the compatibility combined role; production rejects it.
Railway service-level start-command override and private networking must be verified in the actual
project before release.

## Vercel origin/security configuration

Set Vercel's project root to `frontend`, production `VITE_API_URL` to one exact HTTPS Railway API
origin, and configure matching API `CORS_ORIGINS` and `FRONTEND_URL`. The checked-in CSP contains a
deliberate invalid host placeholder; replace it with the exact approved API hostname before build.
Production builds must reject localhost, wildcard origins, unapproved preview domains, and secret
variables prefixed with `VITE_`. Arbitrary preview deployments must not be admitted by production
Railway CORS.

## Required private variables (placeholders only)

Railway API and worker services need the same PostgreSQL URL, hosted key provider and active/prior
version map, separated credential-fingerprint key, application/session/job signing secrets, positive
`HOSTED_SECURITY_EPOCH`, cohort and approved tester identifiers, and the explicit simulated-only
flags `LIVE_TRADING_ENABLED=false` and `PROVIDER_MUTATIONS_ENABLED=false`. Redis URL, exact CORS
origins, trusted proxy configuration, rate-limit settings, and provider API base URL are separate
runtime configuration. Never place a tester's Topstep username/API key in deployment variables;
those are user-owned encrypted database records. Keep keys out of shell arguments and deployment
logs. Store generated values through the Railway dashboard/secret manager and use placeholders in
runbooks.

## Release, health, and rollback

1. Create PostgreSQL and Redis without public exposure; capture backup and restore evidence.
2. Apply Alembic as a controlled release step and verify the single current head.
3. Deploy API with provider mutations disabled; check `/health/live` and `/health/ready`.
4. Deploy the separate worker privately; verify heartbeat and lease handoff after restart.
5. Build/deploy Vercel; verify CSP, exact CORS, authentication, response and bundle scans.
6. Do not invite a tester until policy, consent, read-only provider evidence, recovery, and owner
   approval checks have been completed.

Rollback means stop new API and worker processing, keep provider mutation disabled, preserve the
authoritative PostgreSQL database, and redeploy the prior immutable image only if its migration
compatibility is established. Never restore an old database into service without incrementing
`HOSTED_SECURITY_EPOCH` and completing revoke-by-default reconciliation. No order replay is allowed.

No external backup restore, deployed health check, Railway worker restart, or Vercel build has been
claimed by the local template.
