import type { INestApplicationContext } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { OutboxStatus, Prisma } from '@prisma/client';
import { Queue } from 'bullmq';
import IORedis from 'ioredis';
import { randomUUID } from 'node:crypto';
import {
  AsyncEventType,
  bullMqTransportJobId,
  JobName,
  QueueName,
} from '../../src/async/contracts/async-contracts';
import { EventRouterService } from '../../src/async/contracts/event-router.service';
import { OutboxRelayRepository } from '../../src/async/outbox/outbox-relay.repository';
import { OutboxRelayRunner } from '../../src/async/outbox/outbox-relay.runner';
import { RelayModule } from '../../src/async/relay.module';
import { BullMqPublisherService } from '../../src/async/transport/bullmq-publisher.service';
import { AppConfigService } from '../../src/config/app-config.service';
import { PrismaService } from '../../src/database/prisma.service';

function relayClaim(instanceId: string) {
  return {
    instanceId,
    batchSize: 2,
    claimLeaseMs: 5000,
    maxPublishAttempts: 4,
  };
}

describe('M4.1 outbox relay', () => {
  let app: INestApplicationContext;
  let prisma: PrismaService;
  let runner: OutboxRelayRunner;
  let repository: OutboxRelayRepository;
  let router: EventRouterService;
  let publisher: BullMqPublisherService;
  let config: AppConfigService;
  let redis: IORedis;
  let processingQueue: Queue;

  beforeAll(async () => {
    app = await NestFactory.createApplicationContext(RelayModule, { logger: false });
    prisma = app.get(PrismaService);
    runner = app.get(OutboxRelayRunner);
    repository = app.get(OutboxRelayRepository);
    router = app.get(EventRouterService);
    publisher = app.get(BullMqPublisherService);
    config = app.get(AppConfigService);
    redis = new IORedis(config.redisUrl, { maxRetriesPerRequest: 1 });
    processingQueue = new Queue(QueueName.PROCESSING, { connection: redis, prefix: config.bullMqPrefix });
  });

  beforeEach(async () => {
    await prisma.outboxEvent.deleteMany();
    await redis.flushdb();
  });

  afterAll(async () => {
    await processingQueue.close();
    await redis.quit();
    await app.close();
  });

  it('publishes a validated deterministic BullMQ job then marks the durable event PUBLISHED', async () => {
    const documentId = randomUUID();
    const versionId = randomUUID();
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: versionId,
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        schemaVersion: 1,
        payload: { documentId, documentVersionId: versionId, versionNo: 1 },
      },
    });

    await expect(runner.runOnce()).resolves.toBe(1);

    const persisted = await prisma.outboxEvent.findUniqueOrThrow({ where: { id: event.id } });
    expect(persisted.status).toBe(OutboxStatus.PUBLISHED);
    expect(persisted.publishedAt).not.toBeNull();
    expect(persisted.claimOwner).toBeNull();
    expect(persisted.claimExpiresAt).toBeNull();
    expect(persisted.attempts).toBe(1);

    const jobId = bullMqTransportJobId(JobName.PROCESS_DOCUMENT_VERSION, 1, event.id);
    const job = await processingQueue.getJob(jobId);
    expect(job?.name).toBe(JobName.PROCESS_DOCUMENT_VERSION);
    expect(job?.data).toMatchObject({
      eventId: event.id,
      correlationId: event.id,
      payload: { documentId, documentVersionId: versionId, versionNo: 1 },
    });
    expect(job?.data.payload).not.toHaveProperty('ownerId');
  });

  it('recovers an expired claim after publish-before-mark crash without duplicating the BullMQ job', async () => {
    const documentId = randomUUID();
    const versionId = randomUUID();
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: versionId,
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        payload: { documentId, documentVersionId: versionId, versionNo: 2 },
      },
    });

    const [claimed] = await repository.claimBatch(relayClaim('crashed-relay'));
    expect(claimed?.id).toBe(event.id);
    if (!claimed) throw new Error('Expected event to be claimed');
    const [job] = router.route(claimed);
    if (!job) throw new Error('Expected routed job');
    await publisher.publish(job);

    await prisma.$executeRaw(Prisma.sql`
      UPDATE "outbox_events"
      SET "claim_expires_at" = CURRENT_TIMESTAMP - INTERVAL '1 second'
      WHERE "id" = ${event.id}::uuid
    `);

    await expect(runner.runOnce()).resolves.toBe(1);
    const persisted = await prisma.outboxEvent.findUniqueOrThrow({ where: { id: event.id } });
    expect(persisted.status).toBe(OutboxStatus.PUBLISHED);
    expect(persisted.attempts).toBe(2);

    const counts = await processingQueue.getJobCounts('waiting', 'delayed', 'active', 'completed', 'failed');
    expect(Object.values(counts).reduce((sum, count) => sum + count, 0)).toBe(1);
  });

  it('uses SKIP LOCKED claims so concurrent relay instances do not claim the same event', async () => {
    await prisma.outboxEvent.createMany({
      data: Array.from({ length: 4 }, (_, index) => {
        const versionId = randomUUID();
        return {
          aggregateType: 'DocumentVersion',
          aggregateId: versionId,
          eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
          payload: { documentId: randomUUID(), documentVersionId: versionId, versionNo: index + 1 },
        };
      }),
    });

    const [left, right] = await Promise.all([
      repository.claimBatch(relayClaim('relay-a')),
      repository.claimBatch(relayClaim('relay-b')),
    ]);
    const ids = [...left, ...right].map((event) => event.id);
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
  });

  it('moves due events with exhausted publish attempts to durable FAILED without re-claiming them', async () => {
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: randomUUID(),
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        payload: {},
        attempts: config.outboxRelayMaxPublishAttempts,
      },
    });

    await expect(runner.runOnce()).resolves.toBe(0);
    const persisted = await prisma.outboxEvent.findUniqueOrThrow({ where: { id: event.id } });
    expect(persisted.status).toBe(OutboxStatus.FAILED);
    expect(persisted.lastErrorCode).toBe('OUTBOX_PUBLISH_ATTEMPTS_EXHAUSTED');
  });

  it('marks unknown event contracts FAILED instead of silently coercing them', async () => {
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: randomUUID(),
        eventType: 'UNKNOWN_EVENT',
        schemaVersion: 1,
        payload: {},
      },
    });

    await expect(runner.runOnce()).resolves.toBe(1);
    const persisted = await prisma.outboxEvent.findUniqueOrThrow({ where: { id: event.id } });
    expect(persisted.status).toBe(OutboxStatus.FAILED);
    expect(persisted.lastErrorCode).toBe('ASYNC_EVENT_TYPE_UNSUPPORTED');
    expect(persisted.publishedAt).toBeNull();
  });

  it('enforces outbox state shape at the PostgreSQL boundary', async () => {
    const event = await prisma.outboxEvent.create({
      data: {
        aggregateType: 'DocumentVersion',
        aggregateId: randomUUID(),
        eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
        payload: {},
      },
    });

    await expect(
      prisma.$executeRaw(Prisma.sql`
        UPDATE "outbox_events"
        SET "status" = 'PUBLISHED'::"OutboxStatus"
        WHERE "id" = ${event.id}::uuid
      `),
    ).rejects.toBeDefined();
  });
});
