# M4 Async Foundation

This document describes the durable asynchronous boundary implemented through M4.2.

## M4 split

M4 is intentionally implemented in small slices:

1. **M4.1 — contracts, Redis/BullMQ topology, Outbox Relay** — implemented
2. **M4.2 — worker runtime + consumer dispatch + InboxReceipt** — implemented in this change
3. **M4.3 — retry classification, DeadLetterRecord and durable DLQ policy**
4. **M4.4 — admin replay/requeue + operational observability and hardening**

M4.1 establishes durable at-least-once publication. M4.2 adds the PostgreSQL consumer-side duplicate-effect guard. Neither slice claims end-to-end exactly-once delivery.

## Delivery semantics

End-to-end delivery is **at least once**.

PostgreSQL `OutboxEvent` is the durable source of truth. Redis/BullMQ is transport only. Business request handlers write `PENDING` outbox rows in the same PostgreSQL transaction as the originating business mutation; they do not enqueue BullMQ jobs directly.

Relay claims are short PostgreSQL transactions using `FOR UPDATE SKIP LOCKED` and an expiring lease. The transaction commits before any Redis network call. This intentionally leaves two recoverable crash windows:

- claim committed but publish did not happen: the lease expires and another relay claims the event;
- BullMQ accepted the job but the PostgreSQL `PUBLISHED` mark did not commit: the event is published again.

Duplicate publication is therefore expected. Deterministic BullMQ job identity reduces ordinary transport duplicates, but correctness does not depend on it.

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

BullMQ currently reserves `:` in custom job IDs. Therefore the transport derives a safe ID from the same fields:

`{jobName}~v{contractVersion}~{eventId}`

The canonical logical identity is still logged and treated as the contract identity; the `~` representation exists only at the BullMQ boundary.

## Worker contract validation

Every consumed job is validated again at runtime before handler dispatch. M4.2 fails closed for:

- unsupported `contractVersion`;
- unexpected top-level or payload fields;
- malformed UUID locators;
- mismatched BullMQ queue/job name versus envelope;
- unsupported event/job/queue values;
- aggregate identity that does not match `documentVersionId`;
- malformed positive integer version numbers.

Transport data is not trusted merely because it came from this application's relay.

## Consumer registry

Handlers register a stable logical `consumerName` plus:

- `queueName`;
- `jobName`;
- `contractVersion`.

The registry rejects invalid consumer names, non-positive contract versions and duplicate `(jobName, contractVersion)` registrations at startup. `consumerName` must describe the logical consumer contract; it must not contain a pod, host or replica identifier.

The foundation module intentionally registers no production business handler yet. Concrete processing/learning handlers are added by the milestone that owns their authoritative state transitions rather than inventing placeholder business behavior in M4.

## InboxReceipt durable idempotency

`InboxReceipt` records successful durable consumption with:

- `id`;
- `consumerName`;
- `eventId`;
- `jobName`;
- `contractVersion`;
- `processedAt`;
- optional `resultHash`;
- optional JSON `metadata`.

PostgreSQL enforces a unique receipt identity on:

`(consumerName, eventId, jobName)`

and an FK from `eventId` to `OutboxEvent`.

For PostgreSQL-only handlers, `InboxReceiptService.executeOnce()` provides the correctness boundary:

1. lock the durable `OutboxEvent` row with `SELECT ... FOR UPDATE`;
2. verify the envelope event/aggregate identity matches durable PostgreSQL state;
3. check the stable receipt identity;
4. if a compatible receipt already exists, return a successful deduplicated no-op;
5. otherwise run the handler's PostgreSQL mutation using the same `Prisma.TransactionClient`;
6. insert `InboxReceipt` in that same transaction;
7. commit both the effect and receipt together.

This gives the intended crash behavior:

- crash/throw before commit → effect and receipt both roll back; BullMQ may retry safely;
- commit succeeds but process crashes before acknowledging BullMQ → redelivery finds the receipt and performs no second effect;
- concurrent duplicate deliveries → PostgreSQL row locking serializes the decision and only one effect is committed.

Redis locks are not part of the correctness model.

## External I/O boundary

A `WorkerJobHandler.apply()` receives a `Prisma.TransactionClient`. It must not perform Redis, MinIO, AI, HTTP or other network I/O while that transaction is open.

Workflows requiring external effects need an explicit durable state-machine/CAS boundary owned by their business milestone. An `InboxReceipt` alone cannot make arbitrary external effects exactly once.

## Runtime processes

The relay and worker are separate Nest application contexts with no HTTP routes:

```bash
npm run build
npm run start:relay
npm run start:worker
```

The worker:

- verifies Redis connectivity at startup;
- creates a BullMQ `Worker` only for queues with registered handlers;
- uses configured per-queue concurrency;
- logs committed, deduplicated and failed deliveries with stable event/job identity;
- on SIGTERM/SIGINT stops accepting new work through BullMQ close semantics, waits up to the configured grace period, then force-closes remaining workers if necessary.

The HTTP API does not import either runtime and its health/readiness checks remain independent of Redis.

## Configuration

M4.1 relay configuration:

- `REDIS_URL`
- `BULLMQ_PREFIX`
- `OUTBOX_RELAY_INSTANCE_ID`
- `OUTBOX_RELAY_POLL_INTERVAL_MS`
- `OUTBOX_RELAY_BATCH_SIZE`
- `OUTBOX_RELAY_CLAIM_LEASE_MS`
- `OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS`
- `OUTBOX_RELAY_BACKOFF_BASE_MS`
- `OUTBOX_RELAY_BACKOFF_MAX_MS`

M4.2 worker configuration:

- `WORKER_INSTANCE_ID`
- `WORKER_PROCESSING_CONCURRENCY`
- `WORKER_LEARNING_CONCURRENCY`
- `WORKER_MAINTENANCE_CONCURRENCY`
- `WORKER_SHUTDOWN_GRACE_MS`

All values are validated at startup. Replica instance IDs are operational identities only and are never used as InboxReceipt `consumerName` values.

## M4.2 test invariant

The M4.2 E2E suite uses a test-only PostgreSQL projection table and deliberately submits concurrent jobs with different BullMQ transport IDs but the same durable event identity. This bypasses transport dedupe on purpose and proves that the PostgreSQL receipt boundary, rather than BullMQ job-ID behavior, prevents duplicate durable effects.

The test-only projection does not exist in production migrations.

## Deferred after M4.2

Not implemented yet:

- retryable versus stale versus terminal handler classification;
- durable `DeadLetterRecord` and DLQ policy;
- admin replay/requeue and replay revisions;
- M4 operational lag/DLQ metrics;
- concrete document-processing, quiz, flashcard or analytics business handlers;
- external AI/MinIO processing state machines.
