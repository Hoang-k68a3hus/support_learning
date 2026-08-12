import type { JsonLoggerService } from '../../src/common/logging/json-logger.service';
import type { AppConfigService } from '../../src/config/app-config.service';
import { EventRouterService } from '../../src/async/contracts/event-router.service';
import type { ClaimedOutboxEvent, OutboxRelayRepository } from '../../src/async/outbox/outbox-relay.repository';
import { OutboxRelayRunner } from '../../src/async/outbox/outbox-relay.runner';
import type { BullMqPublisherService } from '../../src/async/transport/bullmq-publisher.service';

const claimed = (attempts: number): ClaimedOutboxEvent => ({
  id: '11111111-1111-4111-8111-111111111111',
  aggregateType: 'DocumentVersion',
  aggregateId: '33333333-3333-4333-8333-333333333333',
  eventType: 'DOCUMENT_VERSION_RECEIVED',
  schemaVersion: 1,
  payload: {
    documentId: '22222222-2222-4222-8222-222222222222',
    documentVersionId: '33333333-3333-4333-8333-333333333333',
    versionNo: 1,
  },
  createdAt: new Date('2026-08-12T08:00:00.000Z'),
  availableAt: new Date('2026-08-12T08:00:00.000Z'),
  attempts,
  claimOwner: 'relay-1',
  claimExpiresAt: new Date('2026-08-12T08:01:00.000Z'),
});

function harness(attempts: number) {
  const event = claimed(attempts);
  const repository = {
    claimBatch: jest.fn().mockResolvedValue([event]),
    markPublished: jest.fn().mockResolvedValue(true),
    rescheduleFailure: jest.fn().mockResolvedValue(true),
    markFailed: jest.fn().mockResolvedValue(true),
  } as unknown as OutboxRelayRepository;
  const publisher = {
    publish: jest.fn().mockRejectedValue(new Error('redis unavailable')),
  } as unknown as BullMqPublisherService;
  const logger = {
    log: jest.fn(),
    error: jest.fn(),
    warn: jest.fn(),
    debug: jest.fn(),
    verbose: jest.fn(),
  } as unknown as JsonLoggerService;
  const config = {
    outboxRelayInstanceId: 'relay-1',
    outboxRelayBatchSize: 20,
    outboxRelayClaimLeaseMs: 5000,
    outboxRelayMaxPublishAttempts: 4,
    outboxRelayBackoffBaseMs: 100,
    outboxRelayBackoffMaxMs: 1000,
    outboxRelayPollIntervalMs: 100,
  } as unknown as AppConfigService;

  return {
    runner: new OutboxRelayRunner(config, repository, new EventRouterService(), publisher, logger),
    repository,
  };
}

describe('OutboxRelayRunner transport failure policy', () => {
  it('reschedules a retryable BullMQ failure using configured exponential backoff', async () => {
    const { runner, repository } = harness(1);
    await expect(runner.runOnce()).resolves.toBe(1);
    expect(repository.rescheduleFailure).toHaveBeenCalledWith({
      eventId: '11111111-1111-4111-8111-111111111111',
      instanceId: 'relay-1',
      errorCode: 'OUTBOX_PUBLISH_TRANSPORT_ERROR',
      delayMs: 100,
    });
    expect(repository.markFailed).not.toHaveBeenCalled();
  });

  it('moves an exhausted BullMQ publish attempt to terminal FAILED', async () => {
    const { runner, repository } = harness(4);
    await expect(runner.runOnce()).resolves.toBe(1);
    expect(repository.markFailed).toHaveBeenCalledWith({
      eventId: '11111111-1111-4111-8111-111111111111',
      instanceId: 'relay-1',
      errorCode: 'OUTBOX_PUBLISH_ATTEMPTS_EXHAUSTED',
    });
    expect(repository.rescheduleFailure).not.toHaveBeenCalled();
  });
});
