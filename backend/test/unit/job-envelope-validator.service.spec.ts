import {
  AsyncEventType,
  JobName,
  QueueName,
} from '../../src/async/contracts/async-contracts';
import { JobEnvelopeValidatorService } from '../../src/worker/job-envelope-validator.service';

const EVENT_ID = '11111111-1111-4111-8111-111111111111';
const DOCUMENT_ID = '22222222-2222-4222-8222-222222222222';
const VERSION_ID = '33333333-3333-4333-8333-333333333333';

function envelope(): Record<string, unknown> {
  return {
    contractVersion: 1,
    eventId: EVENT_ID,
    eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
    jobName: JobName.PROCESS_DOCUMENT_VERSION,
    queueName: QueueName.PROCESSING,
    aggregateType: 'DocumentVersion',
    aggregateId: VERSION_ID,
    occurredAt: '2026-08-12T09:00:00.000Z',
    correlationId: EVENT_ID,
    payload: {
      documentId: DOCUMENT_ID,
      documentVersionId: VERSION_ID,
      versionNo: 2,
    },
  };
}

const delivery = {
  queueName: QueueName.PROCESSING,
  bullMqJobName: JobName.PROCESS_DOCUMENT_VERSION,
  bullMqJobId: 'transport-job-1',
  attempt: 1,
};

describe('JobEnvelopeValidatorService', () => {
  const validator = new JobEnvelopeValidatorService();

  it('accepts the current PROCESS_DOCUMENT_VERSION contract', () => {
    expect(validator.parse(envelope(), delivery)).toMatchObject({
      eventId: EVENT_ID,
      jobName: JobName.PROCESS_DOCUMENT_VERSION,
      queueName: QueueName.PROCESSING,
      aggregateId: VERSION_ID,
      payload: {
        documentId: DOCUMENT_ID,
        documentVersionId: VERSION_ID,
        versionNo: 2,
      },
    });
  });

  it('fails closed for unknown versions, fields, delivery identity, and malformed locators', () => {
    expect(() => validator.parse({ ...envelope(), contractVersion: 2 }, delivery)).toThrow('contract version');
    expect(() => validator.parse({ ...envelope(), extra: true }, delivery)).toThrow('unknown fields');
    expect(() =>
      validator.parse(envelope(), { ...delivery, bullMqJobName: 'OTHER_JOB' }),
    ).toThrow('delivery identity');
    expect(() =>
      validator.parse({ ...envelope(), aggregateId: DOCUMENT_ID }, delivery),
    ).toThrow('aggregateId');
    expect(() =>
      validator.parse({ ...envelope(), payload: { documentId: 'bad', documentVersionId: VERSION_ID, versionNo: 1 } }, delivery),
    ).toThrow('documentId');
  });
});
