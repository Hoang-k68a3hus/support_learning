import { Test, type TestingModule } from '@nestjs/testing';
import { OutboxStatus, Prisma } from '@prisma/client';
import { Queue } from 'bullmq';
import IORedis from 'ioredis';
import { randomUUID } from 'node:crypto';
import {
  AsyncEventType,
  type JobEnvelope,
  JobName,
  QueueName,
} from '../../src/async/contracts/async-contracts';
import { JsonLoggerService } from '../../src/common/logging/json-logger.service';
import { AppConfigService } from '../../src/config/app-config.service';
import { ConfigModule } from '../../src/config/config.module';
import { PrismaModule } from '../../src/database/prisma.module';
import { PrismaService } from '../../src/database/prisma.service';
import { InboxReceiptService } from '../../src/inbox/inbox-receipt.service';
import { ConsumerDispatcherService } from '../../src/worker/consumer-dispatcher.service';
import { ConsumerRegistryService } from '../../src/worker/consumer-registry.service';
import { JobEnvelopeValidatorService } from '../../src/worker/job-envelope-validator.service';
import { WORKER_JOB_HANDLERS, type WorkerJobHandler } from '../../src/worker/worker-job-handler';
import { WorkerRuntimeService } from '../../src/worker/worker-runtime.service';

const CONSUMER_NAME = 'm4-foundation-test-consumer';
const failBeforeReceipt = new Set<string>();

const probeHandler: WorkerJobHandler = {
  consumerName: CONSUMER_NAME,
  queueName: QueueName.PROCESSING,
  jobName: JobName.PROCESS_DOCUMENT_VERSION,
  contractVersion: 1,
  apply: async (envelope, tx) => {
    await tx.$executeRaw(Prisma.sql`
      INSERT INTO "m4_worker_probe_effects" ("event_id", "effect_count")
      VALUES (${envelope.eventId}::uuid, 1)
      ON CONFLICT ("event_id") DO UPDATE
      SET "effect_count" = "m4_worker_probe_effects"."effect_count" + 1
    `);
    if (failBeforeReceipt.has(envelope.eventId)) {
      throw new Error('synthetic crash before receipt commit');
    }
    return { metadata: { projection: 'm4_worker_probe_effects' } };
  },
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForState(queue: Queue, jobId: string, expected: 'completed' | 'failed'): Promise<void> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await queue.getJob(jobId);
    if (job && (await job.getState()) === expected) return;
    await delay(50);
  }
  const finalJob = await queue.getJob(jobId);
  throw new Error(`Job ${jobId} did not reach ${expected}; final state=${finalJob ? await finalJob.getState() : 'missing'}`);
}

function jobEnvelope(input: {
  eventId: string;
  documentId: string;
  versionId: string;
  versionNo: number;
}): JobEnvelope {
  return {
    contractVersion: 1,
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

describe('M4.2 worker runtime and InboxReceipt', () => {
  let moduleRef: TestingModule;
  let prisma: PrismaService;
  let inbox: InboxReceiptService;
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
        JobEnvelopeValidatorService,
        { provide: WORKER_JOB_HANDLERS, useValue: [probeHandler] },
        ConsumerRegistryService,
        ConsumerDispatcherService,
        WorkerRuntimeService,
      ],
    }).compile();
    await moduleRef.init();

    prisma = moduleRef.get(PrismaService);
    inbox = moduleRef.get(InboxReceiptService);
    runtime = moduleRef.get(WorkerRuntimeService);
    config = moduleRef.get(AppConfigService);
    redis = new IORedis(config.redisUrl, { maxRetriesPerRequest: 1 });
    processingQueue = new Queue(QueueName.PROCESSING, { connection: redis, prefix: config.bullMqPrefix });

    await prisma.inboxReceipt.deleteMany();
    await prisma.outboxEvent.deleteMany();
    await redis.flushdb();
    await prisma.$executeRawUnsafe(`
      CREATE TABLE IF NOT EXISTS "m4_worker_probe_effects" (
        "event_id" UUID PRIMARY KEY,
        "effect_count" INTEGER NOT NULL CHECK ("effect_count" > 0)
      )
    `);
    await prisma.$executeRawUnsafe('TRUNCATE TABLE "m4_worker_probe_effects"');
    await runtime.start();
  });

  afterAll(async () => {
    await runtime.stop();
    await processingQueue.close();
    await redis.quit();
    await prisma.inboxReceipt.deleteMany();
    await prisma.outboxEvent.deleteMany();
    await prisma.$executeRawUnsafe('DROP TABLE IF EXISTS "m4_worker_probe_effects"');
    await moduleRef.close();
  });

  async function createDurableEvent(versionNo: number): Promise<{
    eventId: string;
    documentId: string;
    versionId: string;
    envelope: JobEnvelope;
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
      envelope: jobEnvelope({ eventId: event.id, documentId, versionId, versionNo }),
    };
  }

  async function effectCount(eventId: string): Promise<number> {
    const rows = await prisma.$queryRaw<Array<{ effectCount: number }>>(Prisma.sql`
      SELECT "effect_count" AS "effectCount"
      FROM "m4_worker_probe_effects"
      WHERE "event_id" = ${eventId}::uuid
    `);
    return rows[0]?.effectCount ?? 0;
  }

  it('commits one durable effect and one InboxReceipt under concurrent duplicate delivery', async () => {
    const input = await createDurableEvent(1);
    const leftId = `duplicate-left-${input.eventId}`;
    const rightId = `duplicate-right-${input.eventId}`;

    await Promise.all([
      processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.envelope, { jobId: leftId }),
      processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.envelope, { jobId: rightId }),
    ]);
    await Promise.all([
      waitForState(processingQueue, leftId, 'completed'),
      waitForState(processingQueue, rightId, 'completed'),
    ]);

    expect(await effectCount(input.eventId)).toBe(1);
    expect(
      await prisma.inboxReceipt.count({
        where: { consumerName: CONSUMER_NAME, eventId: input.eventId, jobName: JobName.PROCESS_DOCUMENT_VERSION },
      }),
    ).toBe(1);

    const repeatedId = `duplicate-repeat-${input.eventId}`;
    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.envelope, { jobId: repeatedId });
    await waitForState(processingQueue, repeatedId, 'completed');
    expect(await effectCount(input.eventId)).toBe(1);
  });

  it('rolls back the business effect when the handler crashes before receipt commit, then retries safely', async () => {
    const input = await createDurableEvent(2);
    failBeforeReceipt.add(input.eventId);
    const failedId = `crash-before-receipt-${input.eventId}`;
    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.envelope, { jobId: failedId });
    await waitForState(processingQueue, failedId, 'failed');

    expect(await effectCount(input.eventId)).toBe(0);
    expect(await prisma.inboxReceipt.count({ where: { eventId: input.eventId } })).toBe(0);

    failBeforeReceipt.delete(input.eventId);
    const retryId = `retry-after-crash-${input.eventId}`;
    await processingQueue.add(JobName.PROCESS_DOCUMENT_VERSION, input.envelope, { jobId: retryId });
    await waitForState(processingQueue, retryId, 'completed');

    expect(await effectCount(input.eventId)).toBe(1);
    expect(await prisma.inboxReceipt.count({ where: { eventId: input.eventId } })).toBe(1);
  });

  it('fails malformed transport payloads before any durable receipt and detects receipt contract conflicts', async () => {
    const input = await createDurableEvent(3);
    const invalidId = `invalid-envelope-${input.eventId}`;
    await processingQueue.add(
      JobName.PROCESS_DOCUMENT_VERSION,
      { ...input.envelope, unexpectedField: true },
      { jobId: invalidId },
    );
    await waitForState(processingQueue, invalidId, 'failed');
    expect(await prisma.inboxReceipt.count({ where: { eventId: input.eventId } })).toBe(0);

    await inbox.executeOnce(
      {
        consumerName: CONSUMER_NAME,
        eventId: input.eventId,
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        aggregateType: 'DocumentVersion',
        aggregateId: input.versionId,
        jobName: JobName.PROCESS_DOCUMENT_VERSION,
        contractVersion: 1,
      },
      async () => undefined,
    );

    await expect(
      inbox.executeOnce(
        {
          consumerName: CONSUMER_NAME,
          eventId: input.eventId,
          eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
          aggregateType: 'DocumentVersion',
          aggregateId: input.versionId,
          jobName: JobName.PROCESS_DOCUMENT_VERSION,
          contractVersion: 2,
        },
        async () => undefined,
      ),
    ).rejects.toThrow('contract version');
  });

  it('enforces InboxReceipt FK and unique identity at PostgreSQL boundary', async () => {
    await expect(
      prisma.inboxReceipt.create({
        data: {
          consumerName: CONSUMER_NAME,
          eventId: randomUUID(),
          jobName: JobName.PROCESS_DOCUMENT_VERSION,
          contractVersion: 1,
        },
      }),
    ).rejects.toBeDefined();

    const input = await createDurableEvent(4);
    await prisma.inboxReceipt.create({
      data: {
        consumerName: 'db-invariant-consumer',
        eventId: input.eventId,
        jobName: JobName.PROCESS_DOCUMENT_VERSION,
        contractVersion: 1,
      },
    });
    await expect(
      prisma.inboxReceipt.create({
        data: {
          consumerName: 'db-invariant-consumer',
          eventId: input.eventId,
          jobName: JobName.PROCESS_DOCUMENT_VERSION,
          contractVersion: 1,
        },
      }),
    ).rejects.toBeDefined();
  });
});
