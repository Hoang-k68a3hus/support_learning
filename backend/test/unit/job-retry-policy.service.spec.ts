import { JobName, JOB_RETRY_POLICY_KEY } from '../../src/async/contracts/async-contracts';
import {
  calculateJobRetryDelayMs,
  JobRetryPolicyService,
} from '../../src/async/retry/job-retry-policy.service';
import type { AppConfigService } from '../../src/config/app-config.service';

function config(): AppConfigService {
  return {
    workerRetryMaxAttempts: 4,
    workerRetryBackoffBaseMs: 100,
    workerRetryBackoffMaxMs: 250,
    workerRetryJitterRatio: 0.2,
    workerFailedJobRetentionCount: 1000,
  } as AppConfigService;
}

describe('JobRetryPolicyService', () => {
  it('resolves a stable named bounded policy and BullMQ job options', () => {
    const service = new JobRetryPolicyService(config());
    expect(service.forJob(JobName.PROCESS_DOCUMENT_VERSION)).toEqual({
      key: JOB_RETRY_POLICY_KEY,
      maxAttempts: 4,
      backoffBaseMs: 100,
      backoffMaxMs: 250,
      jitterRatio: 0.2,
      failedJobRetentionCount: 1000,
    });
    expect(service.bullMqJobOptions(JOB_RETRY_POLICY_KEY)).toEqual({
      attempts: 4,
      backoff: { type: JOB_RETRY_POLICY_KEY },
      removeOnFail: { count: 1000 },
    });
  });

  it('caps exponential delay and applies downward jitter deterministically', () => {
    const policy = {
      backoffBaseMs: 100,
      backoffMaxMs: 250,
      jitterRatio: 0.2,
    };
    expect(calculateJobRetryDelayMs(policy, 1, 0)).toBe(100);
    expect(calculateJobRetryDelayMs(policy, 2, 0)).toBe(200);
    expect(calculateJobRetryDelayMs(policy, 3, 0)).toBe(250);
    expect(calculateJobRetryDelayMs(policy, 3, 1)).toBe(200);
  });

  it('fails closed for malformed attempts and unknown backoff strategy types', () => {
    const service = new JobRetryPolicyService(config());
    expect(() => calculateJobRetryDelayMs(service.forJob(JobName.PROCESS_DOCUMENT_VERSION), 0)).toThrow('attemptsMade');
    expect(service.calculateBackoff(1, 'UNKNOWN_POLICY')).toBe(-1);
  });
});
