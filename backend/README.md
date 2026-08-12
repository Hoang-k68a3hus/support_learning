# support_learning backend

Production-oriented Node.js application backend for `support_learning`.

## Current milestone state

- **M1 Backend Foundation:** implemented.
- **M2 Identity & Access:** implemented.
- **M3 Knowledge Library:** implemented in the application backend: ownership-aware Workspace/Folder/Tag/Document metadata, immutable DocumentVersion/DocumentSource registration, MinIO staging/final storage boundary, idempotency, audit and transactional outbox persistence.
- **M4 Async Foundation:** not implemented yet; BullMQ/Redis relay and workers are intentionally absent from command handlers.

## Runtime

- Node.js 22 + TypeScript + NestJS 11.
- PostgreSQL through Prisma ORM 6.19.x.
- MinIO/S3-compatible object storage through `StoragePort`.
- API prefix `/api/v1`.
- RFC 9457 Problem Details for REST failures.

Node owns web users/auth/session, library metadata, upload/version source facts and durable web transactions. Python/FastAPI remains responsible for AI/RAG processing and consumes immutable RECEIVED `DocumentVersion` identities later; AI state does not overwrite web document/source state.

## Local development

Requirements: Node.js `>=22.12.0`, npm `>=10`, PostgreSQL 17 recommended, and MinIO for upload flows.

```bash
cd backend
cp .env.example .env
# Replace repository placeholders with local secrets and align DATABASE_URL/MinIO credentials.
npm install
npm run prisma:generate
npm run db:migrate:deploy
npm run db:migrate:status
npm run start:dev
```

Root `docker-compose.yml` provides PostgreSQL and MinIO. The application validates required storage and idempotency settings at boot.

## Security and identity

Public registration creates `STUDENT + ACTIVE`. Access JWTs are short-lived Bearer tokens, but protected requests re-resolve server-side Session state, User status and persisted role. Refresh rotation uses the persisted refresh-token hash plus `rotationVersion` CAS.

M3 never accepts authoritative `ownerId`, current version, version number, upload state or storage object key from clients. Foreign resources resolve as `404`. PostgreSQL composite foreign keys backstop same-owner Folder/Document/WorkspaceSource/DocumentTag relationships.

## Knowledge library

The M3 source lifecycle is:

```text
init-upload -> Document ACTIVE + DocumentVersion UPLOADING + staging source identity
browser PUT -> staging object only
complete -> server copy staging -> immutable final object -> verify final metadata
          -> DB transaction: RECEIVED + monotonic currentVersionId + outbox event
M4 later -> outbox relay -> BullMQ worker -> AI ProcessingRun
```

A WorkspaceSource is a study/RAG scope link and unlinking it never deletes the Document. Folder operations organize metadata only. Tag deletion removes joins only. Document deletion is soft and does not rewrite immutable version/source facts.

See `docs/AUTH_API.md`, `docs/SECURITY.md`, and `docs/KNOWLEDGE_LIBRARY_API.md`.

## Checks

```bash
npm run prisma:generate
npm run db:migrate:deploy
npm run db:migrate:status
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
```

E2E uses a disposable PostgreSQL database and validates DB constraints, ownership, concurrency and state transitions. Storage state-machine E2E injects a deterministic `StoragePort`; MinIO remains behind the same production adapter boundary.
