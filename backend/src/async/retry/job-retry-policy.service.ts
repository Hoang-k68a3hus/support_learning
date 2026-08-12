import { Injectable } from '@nestjs/common';
import type { JobsOptions } from 'bullmq';
import { AsyncContractError } from '../contracts/async-contract.error';
import {
  JOB_RETRY_POLICY_KEY,
  type JobRetryPolicyKey,
  JobName,
} from '../contracts/async-contracts';
import { AppConfigService } from '../../config/app-config.service';

export interface JobRetryPolicy {
  key: JobRetryPolicyKey;
  maxAttempts: number;
  backoffBaseMs: number;
  backoffMaxMs: number;
  jitterRatio: number;
  failedJobRetentionCount: number;
}

export function calculateJobRetryDelayMs(
  policy: Pick<JobRetryPolicy, 'backoffBaseMs' | 'backoffMaxMs' | 'jitterRatio'>,
  attemptsMade: number,
  randomValue = Math.random(),
): number {
  if (!Number.isSafeInteger(attemptsMade) || attemptsMade <= 0) {
    throw new AsyncContractError('WORKER_RETRY_ATTEMPT_INVALID', `Invalid attemptsMade value: ${attemptsMade}`);
  }
  if (!Number.isFinite(randomValue) || randomValue < 0 || randomValue > 1) {
    throw new AsyncContractError('WORKER_RETRY_RANDOM_INVALID', 'Retry jitter random value must be between 0 and 1');
  }

  const exponent = Math.min(attemptsMade - 1, 30);
  const uncapped = policy.backoffBaseMs * 2 ** exponent;
  const capped = Math.min(policy.backoffMaxMs, uncapped);
  const factor = 1 - policy.jitterRatio * randomValue;
  return Math.max(0, Math.round(capped * factor));
}

@Injectable()
export class JobRetryPolicyService {
  constructor(private readonly config: AppConfigService) {}

  forJob(jobName: JobName): JobRetryPolicy {
    if (jobName !== JobName.PROCESS_DOCUMENT_VERSION) {
      throw new AsyncContractError('WORKER_RETRY_POLICY_NOT_FOUND', `No retry policy registered for job ${jobName}`);
    }
    return this.resolve(JOB_RETRY_POLICY_KEY);
  }

  resolve(key: JobRetryPolicyKey): JobRetryPolicy {
    return {
      key,
      maxAttempts: this.config.workerRetryMaxAttempts,
      backoffBaseMs: this.config.workerRetryBackoffBaseMs,
      backoffMaxMs: this.config.workerRetryBackoffMaxMs,
      jitterRatio: this.config.workerRetryJitterRatio,
      failedJobRetentionCount: this.config.workerFailedJobRetentionCount,
    };
  }

  bullMqJobOptions(key: JobRetryPolicyKey): Pick<JobsOptions, 'attempts' | 'backoff' | 'removeOnFail'> {
    const policy = this.resolve(key);
    return {
      attempts: policy.maxAttempts,
      backoff: { type: policy.key },
      removeOnFail: { count: policy.failedJobRetentionCount },
    };
  }

  calculateBackoff(attemptsMade: number, type?: string): number {
    if (type !== JOB_RETRY_POLICY_KEY) {
      return -1;
    }
    return calculateJobRetryDelayMs(this.resolve(JOB_RETRY_POLICY_KEY), attemptsMade);
  }
}
