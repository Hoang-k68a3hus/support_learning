import { EventRouterService } from '../../src/async/contracts/event-router.service';
import {
  AsyncEventType,
  bullMqTransportJobId,
  canonicalJobId,
  JOB_RETRY_POLICY_KEY,
  JobName,
  QueueName,
} from '../../src/async/contracts/async-contracts';

const EVENT_ID = '11111111-1111-4111-8111-111111111111';
const DOCUMENT_ID = '22222222-2222-4222-8222-222222222222';
const VERSION_ID = '33333333-3333-4333-8333-333333333333';
type RouterEvent = Parameters<EventRouterService['route']>[0];

function event(overrides: Partial<RouterEvent> = {}): RouterEvent {
  return {
    id: EVENT_ID,
    aggregateType: 'DocumentVersion',
    aggregateId: VERSION_ID,
    eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
    schemaVersion: 1,
    payload: {
      eventId: EVENT_ID,
      ownerId: '44444444-4444-4444-8444-444444444444',
      documentId: DOCUMENT_ID,
      documentVersionId: VERSION_ID,
      versionNo: 3,
    },
    createdAt: new Date('2026-08-12T08:00:00.000Z'),
    ...overrides,
  };
}

describe('EventRouterService', () => {
  const router = new EventRouterService();

  it('maps DOCUMENT_VERSION_RECEIVED v1 to the canonical processing job and minimizes payload', () => {
    const [job] = router.route(event());
    expect(job).toBeDefined();
    expect(job?.queueName).toBe(QueueName.PROCESSING);
    expect(job?.jobName).toBe(JobName.PROCESS_DOCUMENT_VERSION);
    expect(job?.retryPolicyKey).toBe(JOB_RETRY_POLICY_KEY);
    expect(job?.envelope).toMatchObject({
      contractVersion: 1,
      eventId: EVENT_ID,
      eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
      aggregateType: 'DocumentVersion',
      aggregateId: VERSION_ID,
      correlationId: EVENT_ID,
      payload: {
        documentId: DOCUMENT_ID,
        documentVersionId: VERSION_ID,
        versionNo: 3,
      },
    });
    expect(job?.envelope.payload).not.toHaveProperty('ownerId');
  });

  it('fails closed for unknown event types, schema versions, or malformed payloads', () => {
    expect(() => router.route(event({ eventType: 'UNKNOWN_EVENT' }))).toThrow('Unsupported event type');
    expect(() => router.route(event({ schemaVersion: 2 }))).toThrow('schema version');
    expect(() => router.route(event({ aggregateId: DOCUMENT_ID }))).toThrow('aggregate');
    expect(() => router.route(event({ payload: { documentId: 'bad', documentVersionId: VERSION_ID, versionNo: 1 } }))).toThrow(
      'documentId',
    );
  });
});

describe('deterministic job identity', () => {
  it('keeps the frozen logical identity while using a BullMQ-safe transport ID', () => {
    const logical = canonicalJobId(JobName.PROCESS_DOCUMENT_VERSION, 1, EVENT_ID);
    const transport = bullMqTransportJobId(JobName.PROCESS_DOCUMENT_VERSION, 1, EVENT_ID);
    expect(logical).toBe(`PROCESS_DOCUMENT_VERSION:v1:${EVENT_ID}`);
    expect(transport).toBe(`PROCESS_DOCUMENT_VERSION~v1~${EVENT_ID}`);
    expect(transport).not.toContain(':');
  });
});
