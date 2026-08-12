import { Injectable, type OnModuleDestroy } from '@nestjs/common';
import { type Job, Worker } from 'bullmq';
import IORedis from 'ioredis';
import { QueueName } from '../async/contracts/async-contracts';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { AppConfigService } from '../config/app-config.service';
import { ConsumerDispatcherService } from './consumer-dispatcher.service';
import { ConsumerRegistryService } from './consumer-registry.service';

interface WorkerBinding {
  queueName: QueueName;
  worker: Worker;
  connection: IORedis;
}

@Injectable()
export class WorkerRuntimeService implements OnModuleDestroy {
  private controlConnection?: IORedis;
  private readonly bindings: WorkerBinding[] = [];
  private started = false;
  private stopping?: Promise<void>;
  private readonly stoppedPromise: Promise<void>;
  private resolveStopped!: () => void;

  constructor(
    private readonly config: AppConfigService,
    private readonly registry: ConsumerRegistryService,
    private readonly dispatcher: ConsumerDispatcherService,
    private readonly logger: JsonLoggerService,
  ) {
    this.stoppedPromise = new Promise<void>((resolve) => {
      this.resolveStopped = resolve;
    });
  }

  async start(): Promise<void> {
    if (this.started) return;

    const control = this.createRedisConnection(`support-learning-worker-control:${this.config.workerInstanceId}`, true);
    control.on('error', (error: Error) => this.logger.error('worker_redis_connection_error', { error }));
    await control.connect();
    await control.ping();
    this.controlConnection = control;

    for (const queueName of this.registry.queueNames()) {
      const connection = this.createRedisConnection(
        `support-learning-worker:${this.config.workerInstanceId}:${queueName}`,
        false,
      );
      connection.on('error', (error: Error) => {
        this.logger.error('worker_queue_redis_error', { queueName, error });
      });

      const worker = new Worker(
        queueName,
        async (job: Job) =>
          this.dispatcher.dispatch(job.data as unknown, {
            queueName,
            bullMqJobName: job.name,
            bullMqJobId: job.id,
            attempt: job.attemptsMade + 1,
          }),
        {
          connection,
          prefix: this.config.bullMqPrefix,
          concurrency: this.config.workerConcurrency(queueName),
        },
      );
      worker.on('error', (error: Error) => this.logger.error('worker_runtime_error', { queueName, error }));
      worker.on('failed', (job, error: Error) => {
        this.logger.error('worker_job_failed', {
          queueName,
          bullMqJobId: job?.id,
          bullMqJobName: job?.name,
          attempt: (job?.attemptsMade ?? 0) + 1,
          error,
        });
      });
      this.bindings.push({ queueName, worker, connection });
    }

    this.started = true;
    this.logger.log('worker_runtime_started', {
      workerInstanceId: this.config.workerInstanceId,
      handlerCount: this.registry.registrations().length,
      queues: this.registry.queueNames(),
    });
  }

  async waitUntilStopped(): Promise<void> {
    await this.stoppedPromise;
  }

  async stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    this.stopping = this.stopInternal();
    return this.stopping;
  }

  async onModuleDestroy(): Promise<void> {
    await this.stop();
  }

  private async stopInternal(): Promise<void> {
    const bindings = [...this.bindings];
    const graceful = Promise.all(bindings.map(async ({ worker }) => worker.close(false))).then(() => true);
    const timedOut = new Promise<false>((resolve) => {
      setTimeout(() => resolve(false), this.config.workerShutdownGraceMs).unref();
    });
    const gracefulCompleted = await Promise.race([graceful, timedOut]);

    if (!gracefulCompleted) {
      this.logger.warn('worker_shutdown_grace_exhausted', {
        workerInstanceId: this.config.workerInstanceId,
        graceMs: this.config.workerShutdownGraceMs,
      });
      await Promise.allSettled(bindings.map(async ({ worker }) => worker.close(true)));
    }

    await Promise.allSettled(bindings.map(async ({ connection }) => connection.quit()));
    this.bindings.length = 0;
    if (this.controlConnection) {
      await this.controlConnection.quit();
      this.controlConnection = undefined;
    }
    this.started = false;
    this.resolveStopped();
    this.logger.log('worker_runtime_stopped', { workerInstanceId: this.config.workerInstanceId });
  }

  private createRedisConnection(connectionName: string, failFast: boolean): IORedis {
    return new IORedis(this.config.redisUrl, {
      lazyConnect: true,
      enableOfflineQueue: !failFast,
      maxRetriesPerRequest: failFast ? 1 : null,
      connectionName,
    });
  }
}
