# M4 Async Foundation

This document describes the durable asynchronous boundary implemented through M4.3.

## M4 split

M4 is intentionally implemented in small slices:

1. **M4.1 — contracts, Redis/BullMQ topology, Outbox Relay** — implemented
2. **M4.2 — worker runtime + consumer dispatch + InboxReceipt** — implemented
3. **M4.3 — retry classification, bounded worker retries, DeadLetterRecord and durable DLQ policy** — implemented
4. **M4.4 — admin replay/requeue + operational observability and hardening** — deferred

M4.1 establishes durable at-least-once publication. M4.2 adds the PostgreSQL consumer-side duplicate-effect guard. M4.3 adds bounded failure handling and durable dead-letter state. None of these slices claims end-to-end exactly-once delivery.

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
- `FAILED` — terminal relay contract failure or exhausted publication attempts.

PostgreSQL CHECK constraints enforce state shape. Relay retries update `availableAt`; they never modify the originating business aggregate.

Outbox publication retries and worker business-job retries are deliberately separate policies. A Redis/BullMQ publication failure is not the same failure domain as a handler processing failure.

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

BullMQ currently reserves `:` inside custom job IDs. Therefore the transport derives a safe ID from the same fields:

`{jobName}~v{contractVersion}~{eventId}`

The canonical logical identity is still logged and treated as the contract identity; the `~` representation exists only at the BullMQ boundary.

## Worker contract validation

Every consumed job is validated again at runtime before handler dispatch. The worker fails closed for:

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

The registry rejects invalid consumer names, non-positive contract versions and duplicate `(jobName, contractVersion)` registrations at startup. `consumerName` describes the logical consumer contract; it must not contain a pod, host or replica identifier.

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

- crash/throw before commit → effect and receipt both roll back; BullMQ may redeliver safely;
- commit succeeds but process crashes before acknowledging BullMQ → redelivery finds the receipt and performs no second effect;
- concurrent duplicate deliveries → PostgreSQL row locking serializes the decision and only one effect is committed.

Redis locks are not part of the correctness model.

## M4.3 failure taxonomy

Worker failures are classified by type rather than message matching:

- `RetryableJobError` — transient failure that may recover on a later bounded attempt;
- `TerminalJobError` — deterministic failure that should not consume the remaining retry budget;
- `StaleJobError` — work that is intentionally obsolete and should complete as a durable no-op when raised inside the transactional handler boundary.

Known transient Prisma failures such as connection initialization failures, connection-pool timeout `P2024`, and transaction conflict/deadlock `P2034` are retryable. Async contract violations are terminal. Unclassified errors fail closed as terminal `WORKER_UNCLASSIFIED_ERROR` rather than being retried indefinitely.

Failure classification is explicit application behavior. New dependencies must map their transient/terminal semantics intentionally instead of relying on error-message substrings.

## Bounded worker retry policy

The current `PROCESS_DOCUMENT_VERSION` job maps to the named policy:

`PROCESSING_JOB_EXPONENTIAL_V1`

The relay attaches the following BullMQ options when publishing the job:

- a finite `attempts` count;
- the named custom backoff strategy;
- bounded failed-job retention.

The worker calculates capped exponential delay with configurable downward jitter. It also caps the effective retry budget to the smaller of the code-configured policy and the transport job's `attempts` value, so a manually injected transport job cannot increase the worker retry budget above policy.

Retry timing is controlled by:

- `WORKER_RETRY_MAX_ATTEMPTS`;
- `WORKER_RETRY_BACKOFF_BASE_MS`;
- `WORKER_RETRY_BACKOFF_MAX_MS`;
- `WORKER_RETRY_JITTER_RATIO`;
- `WORKER_FAILED_JOB_RETENTION_COUNT`.

A retryable failure is rethrown while attempts remain. On the final allowed attempt it is converted to durable dead-letter state and the BullMQ job becomes terminally failed.

A terminal failure persists dead-letter state immediately and then uses BullMQ unrecoverable failure semantics so unused attempts are not consumed.

## Stale work is a real no-op

A handler can discover that its target became obsolete only after entering the Inbox transaction. Simply catching `StaleJobError` would be unsafe because the handler may already have made PostgreSQL writes before discovering staleness.

M4.3 therefore wraps the handler body in a PostgreSQL SAVEPOINT inside the existing Inbox transaction:

1. create the savepoint;
2. run the handler;
3. if the handler raises `StaleJobError`, roll back to the savepoint;
4. release the savepoint;
5. insert the normal InboxReceipt with metadata such as `outcome=STALE_NOOP` and the stable stale code;
6. commit the receipt without any partial handler effect.

The stale delivery completes successfully and future duplicates deduplicate against the receipt. A `StaleJobError` that escapes outside this expected transactional boundary is treated as terminal because its rollback guarantee cannot be established.

## Durable DeadLetterRecord

Terminal failures and exhausted retryable failures are represented durably in PostgreSQL by `DeadLetterRecord`.

The record contains:

- `id`;
- `eventId` with FK to the original `OutboxEvent`;
- `jobName`;
- `queueName`;
- `contractVersion`;
- stable `errorCode`;
- `errorMessageRedacted`;
- optional SHA-256 `stackFingerprint`;
- optional SHA-256 `payloadHash`;
- `attempts`;
- `failedAt`;
- `replayCount`;
- `lastReplayAt`;
- `resolvedAt`.

PostgreSQL permits only one unresolved record for `(eventId, jobName)` using a partial unique index. Repeated terminal delivery before resolution updates that active record instead of creating parallel unresolved records. Historical resolved rows are retained, so a later failure may create a new active record.

Dead-letter rows do not copy raw source bytes, authorization snapshots, full job payloads, or stack traces. The job envelope is represented only by a deterministic hash and the error stack only by a fingerprint. Persisted error text is a controlled redacted message.

When a later delivery of the same event/job succeeds, the worker best-effort marks an existing active dead letter `resolvedAt`. Administrative replay counters and explicit replay orchestration remain M4.4 responsibilities.

## DLQ persistence failure boundary

A terminal/exhausted job is not considered durably dead-lettered until its PostgreSQL `DeadLetterRecord` write succeeds.

If that write fails while retry budget remains, the worker returns a typed retryable `DEAD_LETTER_PERSIST_FAILED` failure so a later attempt can preserve durable failure state. If persistence still fails on the final attempt, the BullMQ job remains failed and the worker emits structured error logs; it does not create an unbounded retry loop.

A malformed job with no trustworthy `eventId` cannot create an FK-backed dead letter. In that case the worker fails the transport job terminally and logs `worker_dead_letter_identity_unavailable` rather than inventing an event locator.

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
- validates every job envelope before dispatch;
- enforces bounded named retry policies;
- records stale no-ops, durable dead letters, successful commits and duplicate deliveries with stable event/job identity;
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

M4.2 worker runtime configuration:

- `WORKER_INSTANCE_ID`
- `WORKER_PROCESSING_CONCURRENCY`
- `WORKER_LEARNING_CONCURRENCY`
- `WORKER_MAINTENANCE_CONCURRENCY`
- `WORKER_SHUTDOWN_GRACE_MS`

M4.3 worker retry/DLQ configuration:

- `WORKER_RETRY_MAX_ATTEMPTS`
- `WORKER_RETRY_BACKOFF_BASE_MS`
- `WORKER_RETRY_BACKOFF_MAX_MS`
- `WORKER_RETRY_JITTER_RATIO`
- `WORKER_FAILED_JOB_RETENTION_COUNT`

All values are validated at startup. Replica instance IDs are operational identities only and are never used as InboxReceipt `consumerName` values.

## Test invariants

M4.2 E2E deliberately submits concurrent jobs with different BullMQ transport IDs but the same durable event identity. This bypasses transport dedupe and proves PostgreSQL InboxReceipt prevents duplicate durable effects.

M4.3 E2E uses real PostgreSQL + Redis/BullMQ and proves:

- retryable failure can fail multiple attempts and commit exactly one PostgreSQL effect after recovery;
- retryable failure exhausts exactly the configured finite budget and creates one active DeadLetterRecord;
- terminal failure bypasses remaining attempts and creates durable dead-letter state immediately;
- unsupported contract versions are terminal before handler execution;
- stale work rolls back writes made before `StaleJobError`, commits a stale InboxReceipt, and creates no dead letter;
- repeated terminal delivery has one unresolved `(eventId, jobName)` record;
- after resolution, a later failure can create a new historical dead-letter row.

Test-only PostgreSQL projection tables used by E2E do not exist in production migrations.

## Deferred after M4.3

Not implemented yet:

- M4.4 admin replay/requeue endpoints and replay revision semantics;
- M4.4 operational queue lag, retry and DLQ metrics/hardening;
- concrete document-processing, quiz, flashcard or analytics business handlers;
- external AI/MinIO processing state machines.
