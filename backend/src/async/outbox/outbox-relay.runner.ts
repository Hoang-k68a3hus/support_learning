import { Injectable } from '@nestjs/common';
import { JsonLoggerService } from '../../common/logging/json-logger.service';
import { AppConfigService } from '../../config/app-config.service';
import { AsyncContractError } from '../contracts/async-contract.error';
import { EventRouterService } from '../contracts/event-router.service';
import { BullMqPublisherService } from '../transport/bullmq-publisher.service';
import { calculateOutboxBackoffMs } from './outbox-backoff';
import { type ClaimedOutboxEvent, OutboxRelayRepository } from './outbox-relay.repository';

const TRANSPORT_ERROR_CODE = 'OUTBOX_PUBLISH_TRANSPORT_ERROR';

@Injectable()
export class OutboxRelayRunner {
  private stopRequested = false;

  constructor(
    private readonly config: AppConfigService,
    private readonly repository: OutboxRelayRepository,
    private readonly router: EventRouterService,
    private readonly publisher: BullMqPublisherService,
    private readonly logger: JsonLoggerService,
  ) {}

  stop(): void {
    this.stopRequested = true;
  }

  async run(): Promise<void> {
    this.logger.log('outbox_relay_started', {
      instanceId: this.config.outboxRelayInstanceId,
      batchSize: this.config.outboxRelayBatchSize,
    });
    while (!this.stopRequested) {
      await this.runOnce();
      if (!this.stopRequested) await this.sleep(this.config.outboxRelayPollIntervalMs);
    }
    this.logger.log('outbox_relay_stopped', { instanceId: this.config.outboxRelayInstanceId });
  }

  async runOnce(): Promise<number> {
    const events = await this.repository.claimBatch({
      instanceId: this.config.outboxRelayInstanceId,
      batchSize: this.config.outboxRelayBatchSize,
      claimLeaseMs: this.config.outboxRelayClaimLeaseMs,
      maxPublishAttempts: this.config.outboxRelayMaxPublishAttempts,
    });

    for (const event of events) await this.publishClaimedEvent(event);
    return events.length;
  }

  private async publishClaimedEvent(event: ClaimedOutboxEvent): Promise<void> {
    let jobs;
    try {
      jobs = this.router.route(event);
    } catch (error) {
      if (error instanceof AsyncContractError) {
        await this.markTerminal(event, error.code);
        this.logger.error('outbox_contract_failure', {
          eventId: event.id,
          eventType: event.eventType,
          schemaVersion: event.schemaVersion,
          code: error.code,
        });
        return;
      }
      throw error;
    }

    try {
      for (const job of jobs) {
        const published = await this.publisher.publish(job);
        this.logger.log('outbox_job_published', {
          eventId: event.id,
          jobName: job.jobName,
          queueName: job.queueName,
          logicalJobId: published.logicalJobId,
          bullMqJobId: published.bullMqJobId,
        });
      }
    } catch (error) {
      await this.handleTransportFailure(event, error);
      return;
    }

    const marked = await this.repository.markPublished(event.id, this.config.outboxRelayInstanceId);
    if (!marked) {
      this.logger.warn('outbox_publish_mark_lost_claim', { eventId: event.id });
    }
  }

  private async handleTransportFailure(event: ClaimedOutboxEvent, error: unknown): Promise<void> {
    const exhausted = event.attempts >= this.config.outboxRelayMaxPublishAttempts;
    if (exhausted) {
      await this.markTerminal(event, 'OUTBOX_PUBLISH_ATTEMPTS_EXHAUSTED');
    } else {
      const delayMs = calculateOutboxBackoffMs(
        event.attempts,
        this.config.outboxRelayBackoffBaseMs,
        this.config.outboxRelayBackoffMaxMs,
      );
      const rescheduled = await this.repository.rescheduleFailure({
        eventId: event.id,
        instanceId: this.config.outboxRelayInstanceId,
        errorCode: TRANSPORT_ERROR_CODE,
        delayMs,
      });
      if (!rescheduled) this.logger.warn('outbox_retry_lost_claim', { eventId: event.id });
    }

    this.logger.warn('outbox_publish_failed', {
      eventId: event.id,
      attempt: event.attempts,
      exhausted,
      error: error instanceof Error ? error : new Error('Unknown BullMQ publish failure'),
    });
  }

  private async markTerminal(event: ClaimedOutboxEvent, errorCode: string): Promise<void> {
    const marked = await this.repository.markFailed({
      eventId: event.id,
      instanceId: this.config.outboxRelayInstanceId,
      errorCode,
    });
    if (!marked) this.logger.warn('outbox_terminal_mark_lost_claim', { eventId: event.id, errorCode });
  }

  private async sleep(delayMs: number): Promise<void> {
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
  }
}
