# Bracket Craft Agent Guide

## Repository Layout

- `backend/` is a FastAPI application using async SQLAlchemy and PostgreSQL. Python version in CI: 3.12.
- `frontend/` is a Nuxt 3/Vue/Pinia application. CI uses Node 22 and pnpm 11.8.0.
- `infra/postgres/init/` contains initial database setup; `infra/postgres/migrations/` contains ordered SQL migrations.
- `docker-compose.yml` runs PostgreSQL, the one-shot `db-migrate` job, API, worker, Redis, MinIO, and web services.
- Backend feature boundaries live under `backend/app/modules/`; API routers are registered in `backend/app/main.py`.
- There is no root package manager. Run Python commands from `backend/` and pnpm commands from `frontend/`.

## Local Workflow

```sh
cp .env.example .env
docker compose up --build
```

In a second shell, seed development data when needed:

```sh
docker compose exec api python -m scripts.seed_demo
```

`scripts.seed_demo` is development-only and is not a migration or a production command.

## Verification Commands

Run the same checks as CI:

```sh
python -m pip install -r backend/requirements.txt
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
sh -n infra/postgres/migrate.sh
docker compose config -q
pip-audit -r backend/requirements.txt
cd frontend && pnpm audit --prod --audit-level high
```

The invitation integration tests are opt-in and need a running PostgreSQL database containing the demo account and organization:

```sh
docker compose exec -e RUN_DATABASE_TESTS=1 api pytest -q tests/test_invitations.py
```

If direct pnpm commands fail with Windows/WSL `EPERM` errors while linking `node_modules`, build and run them through the `web` service instead.

## Application Conventions

- Database access is tenant-scoped. Set both RLS session values with `set_rls_context()` inside the transaction before tenant queries.
- The application database role must not be a superuser and must not have `BYPASSRLS`.
- Add schema changes as the next numbered SQL migration. `infra/postgres/migrate.sh` stores SHA-256 checksums and rejects edits to applied migrations.
- Frontend API calls should use `frontend/composables/useApi.ts`; it selects server/client base URLs and carries organization, cookie, and CSRF context.
- Keep development defaults in `.env.example` only. Outside development, change `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, database credentials, storage credentials, and enable `AUTH_COOKIE_SECURE`.

## Known CI and Database Notes

- Keep `aquasecurity/trivy-action@v0.36.0` in CI. The older `v0.28.0` reference fails through its missing `setup-trivy@v0.2.1` dependency.
- A clean PostgreSQL volume has previously failed at existing migration 002 with `cannot drop columns from view`; this is a migration-chain issue before migration 014, not an invitation-test failure.
