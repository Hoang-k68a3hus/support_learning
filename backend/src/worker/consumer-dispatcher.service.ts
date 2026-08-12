import { Injectable } from '@nestjs/common';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { InboxReceiptService } from '../inbox/inbox-receipt.service';
import { ConsumerRegistryService } from './consumer-registry.service';
import {
  type DeliveryIdentity,
  JobEnvelopeValidatorService,
} from './job-envelope-validator.service';

export interface ConsumerDispatchResult {
  deduplicated: boolean;
  receiptId: string;
}

@Injectable()
export class ConsumerDispatcherService {
  constructor(
    private readonly validator: JobEnvelopeValidatorService,
    private readonly registry: ConsumerRegistryService,
    private readonly inbox: InboxReceiptService,
    private readonly logger: JsonLoggerService,
  ) {}

  async dispatch(rawEnvelope: unknown, delivery: DeliveryIdentity): Promise<ConsumerDispatchResult> {
    const envelope = this.validator.parse(rawEnvelope, delivery);
    const handler = this.registry.resolve(envelope.jobName, envelope.contractVersion);
    if (handler.queueName !== envelope.queueName) {
      throw new Error(
        `Worker handler queue mismatch for ${handler.consumerName}: expected ${handler.queueName}, got ${envelope.queueName}`,
      );
    }

    const result = await this.inbox.executeOnce(
      {
        consumerName: handler.consumerName,
        eventId: envelope.eventId,
        eventType: envelope.eventType,
        aggregateType: envelope.aggregateType,
        aggregateId: envelope.aggregateId,
        jobName: envelope.jobName,
        contractVersion: envelope.contractVersion,
      },
      async (tx) => handler.apply(envelope, tx),
    );

    this.logger.log(result.deduplicated ? 'worker_job_deduplicated' : 'worker_job_committed', {
      consumerName: handler.consumerName,
      eventId: envelope.eventId,
      jobName: envelope.jobName,
      queueName: envelope.queueName,
      contractVersion: envelope.contractVersion,
      bullMqJobId: delivery.bullMqJobId,
      attempt: delivery.attempt,
      receiptId: result.receiptId,
    });

    return result;
  }
}
