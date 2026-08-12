import { Test, type TestingModule } from '@nestjs/testing';
import { OutboxStatus, Prisma } from '@prisma/client';
import { Queue, type Job } from 'bullmq';
import IORedis from 'ioredis';
import { randomUUID } from 'node:crypto';
import {
  AsyncEventType,
  type JobEnvelope,
  JOB_RETRY_POLICY_KEY,
  JobName,
  QueueName,
} from '../../src/async/contracts/async-contracts';
import { JobRetryPolicyService } from '../../src/async/retry/job-retry-policy.service';
import { JsonLoggerService } from '../../src/common/logging/json-logger.service';
import { AppConfigService } from '../../src/config/app-config.service';
import { ConfigModule } from '../../src/config/config.module';
import { PrismaModule } from '../../src/database/prisma.module';
import { PrismaService } from '../../src/database/prisma.service';
import { DeadLetterService } from '../../src/dead-letter/dead-letter.service';
import { InboxReceiptService } from '../../src/inbox/inbox-receipt.service';
import { ConsumerDispatcherService } from '../../src/worker/consumer-dispatcher.service';
import { ConsumerRegistryService } from '../../src/worker/consumer-registry.service';
import { RetryableJobError, StaleJobError, TerminalJobError } from '../../src/worker/job-errors';
import { JobEnvelopeValidatorService } from '../../src/worker/job-envelope-validator.service';
import { WORKER_JOB_HANDLERS, type WorkerJobHandler } from '../../src/worker/worker-job-handler';
import { WorkerRuntimeService } from '../../src/worker/worker-runtime.service';

const CONSUMER_NAME = 'm4-retry-dlq-test-consumer';
const retryFailuresRemaining = new Map<string, number>();
const terminalEvents = new Set<string>();
const staleEvents = new Set<string>();
const invocationCounts = new Map<string, number>();

const retryDlqProbeHandler: WorkerJobHandler = {
  consumerName: CONSUMER_NAME,
  queueName: QueueName.PROCESSING,
  jobName: JobName.PROCESS_DOCUMENT_VERSION,
  contractVersion: 1,
  apply: async (envelope, tx) => {
    invocationCounts.set(envelope.eventId, (invocationCounts.get(envelope.eventId) ?? 0) + 1);

    const retryFailures = retryFailuresRemaining.get(envelope.eventId) ?? 0;
    if (retryFailures > 0) {
      retryFailuresRemaining.set(envelope.eventId, retryFailures - 1);
      throw new RetryableJobError('TEST_DEPENDENCY_UNAVAILABLE', 'Synthetic dependency is temporarily unavailable');
    }

    if (terminalEvents.has(envelope.eventId)) {
      throw new TerminalJobError('TEST_TERMINAL_CONTRACT', 'Synthetic terminal contract failure');
    }

    await tx.$executeRaw(Prisma.sql`
      INSERT INTO "m4_retry_dlq_probe_effects" ("event_id", "effect_count")
      VALUES (${envelope.eventId}::uuid, 1)
      ON CONFLICT ("event_id") DO UPDATE
      SET "effect_count" = "m4_retry_dlq_probe_effects"."effect_count" + 1
    `);

    if (staleEvents.has(envelope.eventId)) {
      throw new StaleJobError('TEST_TARGET_STALE', 'Synthetic target is intentionally stale');
    }

    return { metadata: { projection: 'm4_retry_dlq_probe_effects' } };
  },
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForState(queue: Queue, jobId: string, expected: 'completed' | 'failed'): Promise<Job> {
  for (let attempt = 0; attempt < 160; attempt += 1) {
    const job = await queue.getJob(jobId);
    if (job && (await job.getState()) === expected) return job;
    await delay(50);
  }
  const finalJob = await queue.getJob(jobId);
  throw new Error(`Job ${jobId} did not reach ${expected}; final state=${finalJob ? await finalJob.getState() : 'missing'}`);
}

function envelope(input: {
  eventId: string;
  documentId: string;
  versionId: string;
  versionNo: number;
  contractVersion?: number;
}): JobEnvelope {
  return {
    contractVersion: input.contractVersion ?? 1,
    eventId: input.eventId,
    eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
    jobName: JobName.PROCESS_DOCUMENT_VERSION,
    queueName: QueueName.PROCESSING,
    aggregateType: 'DocumentVersion',
    aggregateId: input.versionId,
    occurredAt: new Date().toISOString(),
    correlationId: input.eventId,
    payload: {
      documentId: input.documentId,
      documentVersionId: input.versionId,
      versionNo: input.versionNo,
    },
  };
}

describe('M4.3 retry classification and durable DLQ', () => {
  let moduleRef: TestingModule;
  let prisma: PrismaService;
  let runtime: WorkerRuntimeService;
  let config: AppConfigService;
  let redis: IORedis;
  let processingQueue: Queue;

  beforeAll(async () => {
    moduleRef = await Test.createTestingModule({
      imports: [ConfigModule, PrismaModule],
      providers: [
        JsonLoggerService,
        InboxReceiptService,
        DeadLetterService,
        JobRetryPolicyService,
        JobEnvelopeValidatorService,
        { provide: WORKER_JOB_HANDLERS, useValue: [retryDlqProbeHandler] },
        ConsumerRegistryService,
        ConsumerDispatcherService,
        WorkerRuntimeService,
      ],
    }).compile();
    await moduleRef.init();

    prisma = moduleRef.get(PrismaService);
    runtime = moduleRef.get(WorkerRuntimeService);
    config = moduleRef.get(AppConfigService);
    redis = new IORedis(config.redisUrl, { maxRetriesPerRequest: 1 });
    processingQueue = new Queue(QueueName.PROCESSING, { connection: redis, prefix: config.bullMqPrefix });

    await prisma.deadLetterRecord.deleteMany();
    await prisma.inboxReceipt.deleteMany();
    await prisma.outboxEvent.deleteMany();
    await redis.flushdb();
    await prisma.$executeRawUnsafe(`
      CREATE TABLE IF NOT EXISTS "m4_retry_dlq_probe_effects" (
        "event_id" UUID PRIMARY KEY,
        "effect_count" INTEGER NOT NULL CHECK ("effect_count" > 0)
      )
    `);
    await prisma.$executeRawUnsafe('TRUNCATE TABLE "m4_retry_dlq_probe_effects"');
    await runtime.start();
  });

  afterAll(async () => {
    await runtime.stop();
    await processingQueue.close();
    await redis.quit();
    await prisma.deadLetterRecord.deleteMany();
    await prisma.inboxReceipt.deleteMany();
    await prisma.outboxEvent.deleteMany();
    await prisma.$executeRawUnsafe('DROP TABLE IF EXISTS "m4_retry_dlq_probe_effects"');
    await moduleRef.close();
  });

  beforeEach(() => {
    retryFailuresRemaining.clear();
    terminalEvents.clear();
    staleEvents.clear();
    invocationCounts.clear();
  });

  async function createDurableEvent(versionNo: number): Promise<{
    eventId: string;
    documentId: string;
    versionId: string;
    jobEnvelope: JobEnvelope;
  }> {
    const documentId = randomUUID();
    const versionId = randomUUID();
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: versionId,
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        schemaVersion: 1,
        payload: { documentId, documentVersionId: versionId, versionNo },
        status: OutboxStatus.PUBLISHED,
        publishedAt: new Date(),
      },
    });
    return {
      eventId: event.id,
      documentId,
      versionId,
      jobEnvelope: envelope({ eventId: event.id, documentId, versionId, versionNo }),
    };
  }

  function retryOptions(): {
    attempts: number;
    backoff: { type: string };
    removeOnFail: { count: number };
  } {
    return {
      attempts: config.workerRetryMaxAttempts,
      backoff: { type: JOB_RETRY_POLICY_KEY },
      removeOnFail: { count: config.workerFailedJobRetentionCount },
    };
  }

  async function effectCount(eventId: string): Promise<number> {
    const rows = await prisma.$queryRaw<Array<{ effectCount: number }>>(Prisma.sql`
      SELECT "effect_count" AS "effectCount"
      FROM "m4_retry_dlq_probe_effects"
      WHERE "event_id" = ${eventId}::uuid
    `);
    return rows[0]?.effectCount ?? 0;
  }

  it('retries a typed transient failure with the named bounded policy and commits once after recovery', async () => {
    const input = await createDurableEvent(11);
    retryFailuresRemaining.set(input.eventId, 2);
    const jobId = `retry-success-${input.eventId}`;

    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
      jobId,
      ...retryOptions(),
    });
    const job = await waitForState(processingQueue, jobId, 'completed');

    expect(job.attemptsMade).toBe(3);
    expect(invocationCounts.get(input.eventId)).toBe(3);
    expect(await effectCount(input.eventId)).toBe(1);
    expect(await prisma.inboxReceipt.count({ where: { eventId: input.eventId } })).toBe(1);
    expect(await prisma.deadLetterRecord.count({ where: { eventId: input.eventId, resolvedAt: null } })).toBe(0);
  });

  it('dead-letters an exhausted retryable failure exactly once with redacted failure metadata', async () => {
    const input = await createDurableEvent(12);
    retryFailuresRemaining.set(input.eventId, 100);
    const jobId = `retry-exhausted-${input.eventId}`;

    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
      jobId,
      ...retryOptions(),
    });
    const job = await waitForState(processingQueue, jobId, 'failed');

    expect(job.attemptsMade).toBe(config.workerRetryMaxAttempts);
    expect(invocationCounts.get(input.eventId)).toBe(config.workerRetryMaxAttempts);
    expect(await effectCount(input.eventId)).toBe(0);
    expect(await prisma.inboxReceipt.count({ where: { eventId: input.eventId } })).toBe(0);

    const deadLetter = await prisma.deadLetterRecord.findFirstOrThrow({
      where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
    });
    expect(deadLetter.attempts).toBe(config.workerRetryMaxAttempts);
    expect(deadLetter.errorCode).toBe('TEST_DEPENDENCY_UNAVAILABLE');
    expect(deadLetter.errorMessageRedacted).toBe('Synthetic dependency is temporarily unavailable');
    expect(deadLetter.payloadHash).toMatch(/^[0-9a-f]{64}$/);
    expect(deadLetter.stackFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(deadLetter.replayCount).toBe(0);
    expect(deadLetter.lastReplayAt).toBeNull();
  });

  it('fails a typed terminal error immediately despite remaining BullMQ attempts and creates durable DLQ state', async () => {
    const input = await createDurableEvent(13);
    terminalEvents.add(input.eventId);
    const jobId = `terminal-${input.eventId}`;

    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
      jobId,
      ...retryOptions(),
    });
    const job = await waitForState(processingQueue, jobId, 'failed');

    expect(job.attemptsMade).toBe(1);
    expect(invocationCounts.get(input.eventId)).toBe(1);
    const deadLetter = await prisma.deadLetterRecord.findFirstOrThrow({
      where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
    });
    expect(deadLetter.errorCode).toBe('TEST_TERMINAL_CONTRACT');
    expect(deadLetter.attempts).toBe(1);
  });

  it('rolls back partial handler writes for stale work and commits a durable stale no-op receipt', async () => {
    const input = await createDurableEvent(14);
    staleEvents.add(input.eventId);
    const jobId = `stale-${input.eventId}`;

    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
      jobId,
      ...retryOptions(),
    });
    const job = await waitForState(processingQueue, jobId, 'completed');

    expect(job.attemptsMade).toBe(1);
    expect(invocationCounts.get(input.eventId)).toBe(1);
    expect(await effectCount(input.eventId)).toBe(0);
    const receipt = await prisma.inboxReceipt.findFirstOrThrow({ where: { eventId: input.eventId } });
    expect(receipt.metadata).toMatchObject({ outcome: 'STALE_NOOP', code: 'TEST_TARGET_STALE' });
    expect(await prisma.deadLetterRecord.count({ where: { eventId: input.eventId, resolvedAt: null } })).toBe(0);
  });

  it('dead-letters unsupported contract versions before handler execution and bypasses retry attempts', async () => {
    const input = await createDurableEvent(15);
    const invalidEnvelope = {
      ...input.jobEnvelope,
      contractVersion: 2,
    };
    const jobId = `unsupported-contract-${input.eventId}`;

    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, invalidEnvelope, {
      jobId,
      ...retryOptions(),
    });
    const job = await waitForState(processingQueue, jobId, 'failed');

    expect(job.attemptsMade).toBe(1);
    expect(invocationCounts.get(input.eventId)).toBeUndefined();
    const deadLetter = await prisma.deadLetterRecord.findFirstOrThrow({
      where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
    });
    expect(deadLetter.contractVersion).toBe(2);
    expect(deadLetter.errorCode).toBe('WORKER_CONTRACT_VERSION_UNSUPPORTED');
    expect(deadLetter.errorMessageRedacted).toBe('Async job contract validation failed');
  });

  it('enforces one unresolved dead letter per event/job while allowing a new record after resolution', async () => {
    const input = await createDurableEvent(16);
    terminalEvents.add(input.eventId);

    for (const suffix of ['first', 'second']) {
      const jobId = `terminal-${suffix}-${input.eventId}`;
      await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
        jobId,
        ...retryOptions(),
      });
      await waitForState(processingQueue, jobId, 'failed');
    }

    expect(
      await prisma.deadLetterRecord.count({
        where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
      }),
    ).toBe(1);

    const active = await prisma.deadLetterRecord.findFirstOrThrow({
      where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
    });
    await prisma.deadLetterRecord.update({ where: { id: active.id }, data: { resolvedAt: new Date() } });

    const thirdJobId = `terminal-third-${input.eventId}`;
    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.jobEnvelope, {
      jobId: thirdJobId,
      ...retryOptions(),
    });
    await waitForState(processingQueue, thirdJobId, 'failed');

    expect(
      await prisma.deadLetterRecord.count({
        where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION },
      }),
    ).toBe(2);
    expect(
      await prisma.deadLetterRecord.count({
        where: { eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION, resolvedAt: null },
      }),
    ).toBe(1);
  });
});
