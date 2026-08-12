import { Injectable, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { Queue } from 'bullmq';
import IORedis from 'ioredis';
import { JsonLoggerService } from '../../common/logging/json-logger.service';
import { AppConfigService } from '../../config/app-config.service';
import {
  bullMqTransportJobId,
  canonicalJobId,
  type RoutedJob,
  QueueName,
} from '../contracts/async-contracts';
import { JobRetryPolicyService } from '../retry/job-retry-policy.service';

export interface PublishedJobRef {
  logicalJobId: string;
  bullMqJobId: string;
}

@Injectable()
export class BullMqPublisherService implements OnModuleInit, OnModuleDestroy {
  private connection?: IORedis;
  private readonly queues = new Map<QueueName, Queue>();

  constructor(
    private readonly config: AppConfigService,
    private readonly retryPolicies: JobRetryPolicyService,
    private readonly logger: JsonLoggerService,
  ) {}

  async onModuleInit(): Promise<void> {
    const connection = new IORedis(this.config.redisUrl, {
      lazyConnect: true,
      enableOfflineQueue: false,
      maxRetriesPerRequest: 1,
      connectionName: `support-learning-relay:${this.config.outboxRelayInstanceId}`,
    });
    connection.on('error', (error: Error) => {
      this.logger.error('redis_connection_error', { error });
    });
    await connection.connect();
    this.connection = connection;

    for (const queueName of Object.values(QueueName)) {
      this.queues.set(
        queueName,
        new Queue(queueName, {
          connection,
          prefix: this.config.bullMqPrefix,
        }),
      );
    }
  }

  async onModuleDestroy(): Promise<void> {
    await Promise.all([...this.queues.values()].map(async (queue) => queue.close()));
    this.queues.clear();
    if (this.connection) {
      await this.connection.quit();
      this.connection = undefined;
    }
  }

  async publish(job: RoutedJob): Promise<PublishedJobRef> {
    const queue = this.queues.get(job.queueName);
    if (!queue) throw new Error(`BullMQ queue is not initialized: ${job.queueName}`);

    const logicalJobId = canonicalJobId(job.jobName, job.envelope.contractVersion, job.envelope.eventId);
    const bullMqJobId = bullMqTransportJobId(job.jobName, job.envelope.contractVersion, job.envelope.eventId);
    const retryOptions = this.retryPolicies.bullMqJobOptions(job.retryPolicyKey);
    await queue.add(job.jobName, job.envelope, { jobId: bullMqJobId, ...retryOptions });
    return { logicalJobId, bullMqJobId };
  }
}
