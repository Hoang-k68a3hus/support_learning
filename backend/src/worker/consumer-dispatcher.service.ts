import { Injectable } from '@nestjs/common';
import { UnrecoverableError } from 'bullmq';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { DeadLetterService } from '../dead-letter/dead-letter.service';
import { InboxReceiptService } from '../inbox/inbox-receipt.service';
import { classifyJobFailure, type ClassifiedJobFailure } from './job-failure-classifier';
import { RetryableJobError, TerminalJobError } from './job-errors';
import { ConsumerRegistryService } from './consumer-registry.service';
import {
  type DeliveryIdentity,
  JobEnvelopeValidatorService,
} from './job-envelope-validator.service';
import type { JobEnvelope } from '../async/contracts/async-contracts';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STALE_SAVEPOINT = 'worker_stale_guard';

export interface ConsumerDispatchResult {
  deduplicated: boolean;
  receiptId: string;
}

interface DeadLetterIdentity {
  eventId: string;
  jobName: string;
  queueName: string;
  contractVersion: number;
}

@Injectable()
export class ConsumerDispatcherService {
  constructor(
    private readonly validator: JobEnvelopeValidatorService,
    private readonly registry: ConsumerRegistryService,
    private readonly inbox: InboxReceiptService,
    private readonly deadLetters: DeadLetterService,
    private readonly logger: JsonLoggerService,
  ) {}

  async dispatch(rawEnvelope: unknown, delivery: DeliveryIdentity): Promise<ConsumerDispatchResult> {
    let envelope: JobEnvelope | undefined;
    try {
      envelope = this.validator.parse(rawEnvelope, delivery);
      const handler = this.registry.resolve(envelope.jobName, envelope.contractVersion);
      if (handler.queueName !== envelope.queueName) {
        throw new TerminalJobError(
          'WORKER_HANDLER_QUEUE_MISMATCH',
          'Worker handler queue does not match the validated job envelope',
        );
      }

      let staleFailure: ClassifiedJobFailure | undefined;
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
        async (tx) => {
          await tx.$executeRawUnsafe(`SAVEPOINT ${STALE_SAVEPOINT}`);
          try {
            const effectResult = await handler.apply(envelope as JobEnvelope, tx);
            await tx.$executeRawUnsafe(`RELEASE SAVEPOINT ${STALE_SAVEPOINT}`);
            return effectResult;
          } catch (error) {
            const failure = classifyJobFailure(error);
            if (failure.kind !== 'STALE') throw error;

            await tx.$executeRawUnsafe(`ROLLBACK TO SAVEPOINT ${STALE_SAVEPOINT}`);
            await tx.$executeRawUnsafe(`RELEASE SAVEPOINT ${STALE_SAVEPOINT}`);
            staleFailure = failure;
            return {
              metadata: {
                outcome: 'STALE_NOOP',
                code: failure.code,
              },
            };
          }
        },
      );

      await this.resolveDeadLetterBestEffort(envelope, delivery);
      if (staleFailure && !result.deduplicated) {
        this.logger.log('worker_job_stale_noop', {
          consumerName: handler.consumerName,
          eventId: envelope.eventId,
          jobName: envelope.jobName,
          queueName: envelope.queueName,
          contractVersion: envelope.contractVersion,
          bullMqJobId: delivery.bullMqJobId,
          attempt: delivery.attempt,
          code: staleFailure.code,
          receiptId: result.receiptId,
        });
      } else {
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
      }

      return result;
    } catch (error) {
      const failure = classifyJobFailure(error);
      if (failure.kind === 'STALE') {
        throw new TerminalJobError(
          'WORKER_STALE_OUTSIDE_HANDLER_BOUNDARY',
          'StaleJobError escaped the transactional handler boundary',
        );
      }
      return this.handleFailure(rawEnvelope, envelope, delivery, failure);
    }
  }

  private async handleFailure(
    rawEnvelope: unknown,
    envelope: JobEnvelope | undefined,
    delivery: DeliveryIdentity,
    failure: ClassifiedJobFailure,
  ): Promise<never> {
    if (failure.kind === 'RETRYABLE' && delivery.attempt < delivery.maxAttempts) {
      this.logger.warn('worker_job_retryable_failure', {
        eventId: envelope?.eventId ?? this.extractDeadLetterIdentity(rawEnvelope, delivery)?.eventId,
        jobName: envelope?.jobName ?? delivery.bullMqJobName,
        queueName: delivery.queueName,
        contractVersion: envelope?.contractVersion,
        bullMqJobId: delivery.bullMqJobId,
        attempt: delivery.attempt,
        maxAttempts: delivery.maxAttempts,
        code: failure.code,
      });
      throw failure.error;
    }

    const identity = envelope
      ? {
          eventId: envelope.eventId,
          jobName: envelope.jobName,
          queueName: envelope.queueName,
          contractVersion: envelope.contractVersion,
        }
      : this.extractDeadLetterIdentity(rawEnvelope, delivery);

    if (!identity) {
      this.logger.error('worker_dead_letter_identity_unavailable', {
        bullMqJobId: delivery.bullMqJobId,
        bullMqJobName: delivery.bullMqJobName,
        queueName: delivery.queueName,
        attempt: delivery.attempt,
        maxAttempts: delivery.maxAttempts,
        code: failure.code,
      });
      throw new UnrecoverableError(`${failure.code}: durable event identity unavailable`);
    }

    let deadLetterId: string;
    try {
      deadLetterId = await this.deadLetters.persistActive({
        eventId: identity.eventId,
        jobName: identity.jobName,
        queueName: identity.queueName,
        contractVersion: identity.contractVersion,
        errorCode: failure.code,
        errorMessageRedacted: failure.messageRedacted,
        attempts: delivery.attempt,
        rawEnvelope,
        error: failure.error,
      });
    } catch (deadLetterError) {
      const persistenceFailure = classifyJobFailure(deadLetterError);
      this.logger.error('worker_dead_letter_persist_failed', {
        eventId: identity.eventId,
        jobName: identity.jobName,
        queueName: identity.queueName,
        bullMqJobId: delivery.bullMqJobId,
        attempt: delivery.attempt,
        maxAttempts: delivery.maxAttempts,
        originalCode: failure.code,
        persistenceCode: persistenceFailure.code,
      });
      if (delivery.attempt < delivery.maxAttempts) {
        throw new RetryableJobError(
          'DEAD_LETTER_PERSIST_FAILED',
          'Durable dead-letter persistence failed; retrying to preserve failure state',
        );
      }
      throw new UnrecoverableError('DEAD_LETTER_PERSIST_FAILED: durable DLQ persistence exhausted');
    }

    this.logger.error('worker_job_dead_lettered', {
      deadLetterId,
      eventId: identity.eventId,
      jobName: identity.jobName,
      queueName: identity.queueName,
      contractVersion: identity.contractVersion,
      bullMqJobId: delivery.bullMqJobId,
      attempt: delivery.attempt,
      maxAttempts: delivery.maxAttempts,
      code: failure.code,
      failureKind: failure.kind,
    });
    throw new UnrecoverableError(`${failure.code}: ${failure.messageRedacted}`);
  }

  private extractDeadLetterIdentity(rawEnvelope: unknown, delivery: DeliveryIdentity): DeadLetterIdentity | undefined {
    if (rawEnvelope === null || Array.isArray(rawEnvelope) || typeof rawEnvelope !== 'object') return undefined;
    const raw = rawEnvelope as Record<string, unknown>;
    const eventId = raw.eventId;
    const contractVersion = raw.contractVersion;
    if (typeof eventId !== 'string' || !UUID_PATTERN.test(eventId)) return undefined;
    if (typeof contractVersion !== 'number' || !Number.isSafeInteger(contractVersion) || contractVersion <= 0) {
      return undefined;
    }
    if (delivery.bullMqJobName.length === 0 || delivery.bullMqJobName.length > 120) return undefined;
    return {
      eventId,
      jobName: delivery.bullMqJobName,
      queueName: delivery.queueName,
      contractVersion,
    };
  }

  private async resolveDeadLetterBestEffort(envelope: JobEnvelope, delivery: DeliveryIdentity): Promise<void> {
    try {
      const resolved = await this.deadLetters.resolveAfterSuccessfulConsumption(envelope.eventId, envelope.jobName);
      if (resolved > 0) {
        this.logger.log('worker_dead_letter_auto_resolved', {
          eventId: envelope.eventId,
          jobName: envelope.jobName,
          queueName: envelope.queueName,
          contractVersion: envelope.contractVersion,
          bullMqJobId: delivery.bullMqJobId,
          resolvedCount: resolved,
        });
      }
    } catch {
      this.logger.error('worker_dead_letter_auto_resolve_failed', {
        eventId: envelope.eventId,
        jobName: envelope.jobName,
        queueName: envelope.queueName,
        bullMqJobId: delivery.bullMqJobId,
      });
    }
  }
}
