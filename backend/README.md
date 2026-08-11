# support_learning backend

Production-oriented Node.js application backend foundation for `support_learning`.

## Architecture

- **Runtime:** Node.js 22 + TypeScript + NestJS 11.
- **Database:** PostgreSQL, accessed through Prisma ORM 6.19.x.
- **Schema authority:** committed Prisma schema + SQL migrations. Runtime schema synchronization is not used.
- **Application boundary:** this service owns users, authentication, sessions, authorization and future web business modules. AI/RAG internals remain in the Python/FastAPI service.
- **API prefix:** `/api/v1`.

The repository's older Web design document still names Spring Boot. The current implementation mission explicitly supersedes that framework choice with Node.js/TypeScript while preserving its business/security boundaries.

## Requirements

- Node.js `>=22.12.0`
- npm `>=10`
- PostgreSQL 17 recommended for local development; Prisma supports other supported PostgreSQL versions.
- Docker + Docker Compose are optional but recommended for the local database workflow.

## Local development

From the repository root:

```bash
cp .env.example .env
# Replace POSTGRES_PASSWORD=REPLACE_ME with a local-only password.
docker compose up -d postgres
```

Then:

```bash
cd backend
cp .env.example .env
# Set DATABASE_URL to the same local password and generate two independent JWT secrets.
npm install
npm run prisma:generate
npm run db:migrate:deploy
npm run db:migrate:status
npm run start:dev
```

The application fails fast if critical configuration is absent or invalid. There are no fallback JWT secrets.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `NODE_ENV` | yes | `development`, `test`, or `production` |
| `PORT` | yes | API listen port |
| `DATABASE_URL` | yes | PostgreSQL connection URL |
| `JWT_ACCESS_SECRET` | yes | access-token signing secret, >= 32 chars |
| `JWT_ACCESS_TTL` | yes | e.g. `15m`; must be shorter than refresh TTL |
| `JWT_REFRESH_SECRET` | yes | distinct refresh-token signing secret, >= 32 chars |
| `JWT_REFRESH_TTL` | yes | e.g. `7d` |
| `CORS_ORIGIN` | yes | comma-separated explicit origins; wildcard is rejected |

## Database commands

```bash
npm run prisma:generate
npm run db:migrate:dev      # create a migration during schema development
npm run db:migrate:deploy   # apply committed migrations
npm run db:migrate:status
```

Production must use `db:migrate:deploy`; do not use schema auto-synchronization.

## Checks

```bash
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
```

E2E tests require a disposable PostgreSQL database in `DATABASE_URL`. They delete `sessions` and `users`; never point them at shared or production data.

## Health

- `GET /api/v1/health/live` — process liveness only.
- `GET /api/v1/health/ready` — verifies PostgreSQL with `SELECT 1`; returns 503 if the required DB dependency is unavailable.

## Identity and authorization

Public registration creates `STUDENT` only. `ADMIN` is a controlled role reserved for a trusted administrative process that is intentionally outside this milestone. Protected endpoints use a reusable JWT guard; role-restricted endpoints can add `@Roles(Role.ADMIN)` with `RolesGuard`. The principal contains `userId`, `sessionId`, and `role`, which leaves a clean hook for later object ownership checks.

See [`docs/AUTH_API.md`](docs/AUTH_API.md) and [`docs/SECURITY.md`](docs/SECURITY.md).
