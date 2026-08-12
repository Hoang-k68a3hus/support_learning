import { Inject, Injectable, type OnModuleInit } from '@nestjs/common';
import { AsyncContractError } from '../async/contracts/async-contract.error';
import type { JobName, QueueName } from '../async/contracts/async-contracts';
import { WORKER_JOB_HANDLERS, type WorkerJobHandler } from './worker-job-handler';

const CONSUMER_NAME_PATTERN = /^[A-Za-z0-9._:-]+$/;

@Injectable()
export class ConsumerRegistryService implements OnModuleInit {
  private readonly byContract = new Map<string, WorkerJobHandler>();

  constructor(@Inject(WORKER_JOB_HANDLERS) private readonly handlers: readonly WorkerJobHandler[]) {}

  onModuleInit(): void {
    this.byContract.clear();
    for (const handler of this.handlers) {
      if (
        handler.consumerName.length === 0 ||
        handler.consumerName.length > 160 ||
        !CONSUMER_NAME_PATTERN.test(handler.consumerName)
      ) {
        throw new AsyncContractError(
          'WORKER_CONSUMER_NAME_INVALID',
          `Invalid stable consumerName: ${handler.consumerName}`,
        );
      }
      if (!Number.isSafeInteger(handler.contractVersion) || handler.contractVersion <= 0) {
        throw new AsyncContractError(
          'WORKER_HANDLER_CONTRACT_INVALID',
          `Invalid handler contractVersion for ${handler.consumerName}`,
        );
      }
      const key = this.key(handler.jobName, handler.contractVersion);
      if (this.byContract.has(key)) {
        throw new AsyncContractError('WORKER_HANDLER_DUPLICATE', `Duplicate worker handler registration: ${key}`);
      }
      this.byContract.set(key, handler);
    }
  }

  resolve(jobName: JobName, contractVersion: number): WorkerJobHandler {
    const handler = this.byContract.get(this.key(jobName, contractVersion));
    if (!handler) {
      throw new AsyncContractError(
        'WORKER_HANDLER_NOT_REGISTERED',
        `No worker handler registered for ${jobName}:v${contractVersion}`,
      );
    }
    return handler;
  }

  registrations(): readonly WorkerJobHandler[] {
    return [...this.byContract.values()];
  }

  queueNames(): QueueName[] {
    return [...new Set(this.registrations().map((handler) => handler.queueName))];
  }

  private key(jobName: JobName, contractVersion: number): string {
    return `${jobName}:v${contractVersion}`;
  }
}
