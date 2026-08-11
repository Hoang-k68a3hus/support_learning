# support_learning backend

Production-oriented Node.js application backend foundation for `support_learning`.

## Architecture

- **Runtime:** Node.js 22 + TypeScript + NestJS 11.
- **Database:** PostgreSQL, accessed through Prisma ORM 6.19.x.
- **Schema authority:** committed Prisma schema + SQL migrations. Runtime schema synchronization is not used.
- **Application boundary:** this service owns web users, authentication, server-side sessions, authorization and later web business modules. AI/RAG internals remain owned by the Python/FastAPI side.
- **API prefix:** `/api/v1`.
- **Public error contract:** RFC 9457 Problem Details with stable `code` and `requestId` extensions.

## M1/M2 identity contract

`User` keeps the display email separately from `normalizedEmail`, which is the unique lookup identity (`trim + lowercase` for this product). New users are `STUDENT + ACTIVE`. `User.status` is `ACTIVE | SUSPENDED` and authentication paths re-read persisted account/session state instead of treating JWT claims as the revocation database.

`Session` is server-side state. It stores only a SHA-256 hash of the signed refresh token plus `rotationVersion`, expiry, revocation and last-used timestamps. Refresh rotation uses a compare-and-swap on both the current hash and rotation version; concurrent reuse has one winner.

Access JWTs are short-lived Bearer tokens. Protected requests verify the JWT and then re-resolve the current Session, `User.status`, and persisted role. Logout therefore invalidates an existing access token immediately on the next protected request, and a suspended account is rejected by login, refresh, and access checks.

Administrative suspension/unsuspension commands are deliberately not exposed by M2. When M10 adds those commands, suspension must atomically change status, revoke active sessions, and write the required audit record; unsuspension must never resurrect revoked sessions.

## Requirements

- Node.js `>=22.12.0`
- npm `>=10`
- PostgreSQL 17 recommended for local development.
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
# Replace every JWT placeholder with independent random secrets.
npm install
npm run prisma:generate
npm run db:migrate:deploy
npm run db:migrate:status
npm run start:dev
```

The application fails fast if critical configuration is absent, malformed, uses wildcard CORS, reuses a JWT secret, or leaves a known placeholder/example JWT secret in place.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `NODE_ENV` | yes | `development`, `test`, or `production` |
| `PORT` | yes | API listen port |
| `DATABASE_URL` | yes | PostgreSQL connection URL |
| `JWT_ACCESS_SECRET` | yes | random access-token signing secret, >= 32 chars |
| `JWT_ACCESS_TTL` | yes | e.g. `15m`; must be shorter than refresh TTL |
| `JWT_REFRESH_SECRET` | yes | distinct random refresh-token signing secret, >= 32 chars |
| `JWT_REFRESH_TTL` | yes | e.g. `7d` |
| `CORS_ORIGIN` | yes | comma-separated explicit origins; wildcard is rejected |

## Database commands

```bash
npm run prisma:generate
npm run db:migrate:dev
npm run db:migrate:deploy
npm run db:migrate:status
```

Production must use committed migrations via `db:migrate:deploy`; do not use runtime schema synchronization.

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

## Security boundaries

Public registration accepts only email + password and always creates `STUDENT + ACTIVE`; client-supplied profile/role/status fields are rejected. Passwords use the centralized versioned Argon2id policy. Refresh tokens are HttpOnly cookies with `SameSite=Lax`, `Secure` in production, and a narrow auth path. Historical refresh-token-family reuse detection remains an explicit graduation-MVP residual risk; current-token replay is rejected by the Session CAS.

See [`docs/AUTH_API.md`](docs/AUTH_API.md) and [`docs/SECURITY.md`](docs/SECURITY.md).
