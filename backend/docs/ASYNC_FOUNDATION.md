# M4 Async Foundation

This document describes the durable asynchronous boundary implemented in M4.1.

## M4 split

M4 is intentionally implemented in small slices:

1. **M4.1 — contracts, Redis/BullMQ topology, Outbox Relay** (this change)
2. **M4.2 — worker runtime + consumer dispatch + InboxReceipt**
3. **M4.3 — retry classification, DeadLetterRecord and durable DLQ policy**
4. **M4.4 — admin replay/requeue + operational observability and hardening**

M4.1 does not contain business workers and does not claim exactly-once execution.

## Delivery semantics

End-to-end delivery is **at least once**.

PostgreSQL `OutboxEvent` is the durable source of truth. Redis/BullMQ is transport only. Business request handlers continue to write `PENDING` outbox rows in the same PostgreSQL transaction as the originating business mutation; they do not enqueue BullMQ jobs directly.

Relay claims are short PostgreSQL transactions using `FOR UPDATE SKIP LOCKED` and an expiring lease. The transaction commits before any Redis network call. This intentionally leaves two recoverable crash windows:

- claim committed but publish did not happen: the lease expires and another relay claims the event;
- BullMQ accepted the job but the PostgreSQL `PUBLISHED` mark did not commit: the event is published again.

Duplicate publication is expected. Deterministic job identity is transport-level dedupe only; M4.2 `InboxReceipt` will become the durable duplicate-effect guard.

## Outbox state machine

`OutboxEvent.status` is one of:

- `PENDING` — eligible when `availableAt <= database now()`;
- `PUBLISHING` — owned by `claimOwner` until `claimExpiresAt`;
- `PUBLISHED` — BullMQ publication completed and `publishedAt` is durable;
- `FAILED` — terminal contract failure or exhausted publication attempts.

PostgreSQL CHECK constraints enforce state shape. Relay retries update `availableAt`; they never modify the originating business aggregate.

## Queue topology

Stable queues are deliberately small:

- `processing`
- `learning`
- `maintenance`

Only `processing` is routed by the currently implemented M3 event. Future milestones add mappings only when the corresponding business contracts exist.

Redis keys use the configured BullMQ prefix. Do not set ioredis `keyPrefix`; BullMQ owns its own prefix mechanism.

## Job contract

The first canonical mapping is:

`DOCUMENT_VERSION_RECEIVED:v1` → `processing / PROCESS_DOCUMENT_VERSION:v1`

The worker payload contains only:

- `documentId`
- `documentVersionId`
- `versionNo`

It intentionally drops `ownerId` and other authorization snapshots. Workers must re-resolve authoritative state from PostgreSQL.

The architecture-level deterministic identity remains:

`{jobName}:v{contractVersion}:{eventId}`

BullMQ currently reserves `:` in custom job IDs. Therefore M4.1 derives a transport-safe ID from the same fields:

`{jobName}~v{contractVersion}~{eventId}`

The canonical logical identity is still logged and treated as the contract identity; the `~` representation exists only at the BullMQ boundary.

## Runtime

The relay is a separate Nest application context with no HTTP routes:

```bash
npm run build
npm run start:relay
```

It needs PostgreSQL and Redis. The HTTP API does not import the relay module and its health/readiness checks remain independent of Redis.

## Configuration

Required configuration:

- `REDIS_URL`
- `BULLMQ_PREFIX`
- `OUTBOX_RELAY_INSTANCE_ID`
- `OUTBOX_RELAY_POLL_INTERVAL_MS`
- `OUTBOX_RELAY_BATCH_SIZE`
- `OUTBOX_RELAY_CLAIM_LEASE_MS`
- `OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS`
- `OUTBOX_RELAY_BACKOFF_BASE_MS`
- `OUTBOX_RELAY_BACKOFF_MAX_MS`

All values are validated at startup. Production replicas should supply a unique stable relay instance ID, for example the Kubernetes pod name.

## Non-goals of M4.1

Not implemented yet:

- BullMQ Worker processes;
- InboxReceipt and consumer idempotency;
- handler retryability/stale/terminal classification;
- durable DeadLetterRecord;
- admin replay/requeue endpoints;
- business handlers for document processing, quiz, flashcards or study projections.
