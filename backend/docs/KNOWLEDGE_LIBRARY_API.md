# M3 Knowledge Library API

M3 owns authenticated web metadata and immutable source-version registration. It does not parse documents or build RAG indexes.

## Ownership

Every endpoint derives `ownerId` from the authenticated principal. Foreign-owned resources are queried with the owner predicate and return `404`. `WorkspaceSource` and `DocumentTag` also carry `ownerId` so PostgreSQL composite foreign keys reject cross-owner links when application validation is bypassed.

## Resource APIs

- `POST/GET /api/v1/workspaces`
- `GET/PATCH/DELETE /api/v1/workspaces/:id`
- `PUT/DELETE /api/v1/workspaces/:id/sources/:documentId`
- `POST/GET /api/v1/folders`
- `PATCH/DELETE /api/v1/folders/:id`
- `POST/GET /api/v1/tags`
- `PATCH/DELETE /api/v1/tags/:id`
- `GET /api/v1/documents`
- `GET/PATCH/DELETE /api/v1/documents/:id`
- `GET /api/v1/documents/:id/versions`
- `GET /api/v1/documents/:id/status`
- `PUT/DELETE /api/v1/documents/:id/tags/:tagId`

Folder deletion is non-recursive and returns `409` while active child folders or documents exist. Workspace/source unlink and tag deletion never delete the underlying Document, DocumentVersion or DocumentSource.

## Upload lifecycle

### `POST /api/v1/documents/init-upload`

Requires `Idempotency-Key`. Body:

```json
{
  "title": "Lecture notes",
  "folderId": "optional-uuid",
  "originalFilename": "notes.pdf",
  "mediaType": "application/pdf",
  "sizeBytes": 123456
}
```

The transaction creates an ACTIVE Document with no current version, Version `1` in `UPLOADING`, a server-owned staging/final object identity and an IdempotencyRecord. The presigned URL is produced only after commit and targets the staging key. No processing outbox event exists yet.

### `POST /api/v1/documents/:documentId/versions/init-upload`

Also requires `Idempotency-Key`. The server locks the owned ACTIVE Document before allocating the next `versionNo`; clients cannot choose a version number or object key.

### `POST /api/v1/documents/:documentId/versions/:versionId/complete`

The server verifies staging metadata, copies staging to the final immutable object key, verifies that final object and then enters a short PostgreSQL transaction. That transaction changes `UPLOADING -> RECEIVED`, persists verified final metadata, monotonically promotes `currentVersionId` only when the completed version is newer, and inserts `DOCUMENT_VERSION_RECEIVED` into the outbox.

Completing an already RECEIVED version re-verifies the final object and returns the same state without writing another outbox event. An older version may finish after a newer version and remain RECEIVED history; it never moves the current pointer backward.

## Durable boundaries

- PostgreSQL is authoritative for ownership, source version state, joins, idempotency, audit and the M3 outbox row.
- MinIO stores staging and final source bytes. Browser write authority is only ever granted to staging keys.
- BullMQ is intentionally absent from M3 command handlers. M4 will relay the committed outbox to Redis/BullMQ.
- `DocumentVersion` identifies source facts. AI processing state must live in separate processing records and must not rewrite web document state.

## Error contract

REST failures use RFC 9457 Problem Details. M3 adds stable domain codes such as `IDEMPOTENCY_CONFLICT`, `UPLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `UPLOAD_SOURCE_MISSING` and `DATA_INTEGRITY_CONFLICT` while preserving the request ID.
