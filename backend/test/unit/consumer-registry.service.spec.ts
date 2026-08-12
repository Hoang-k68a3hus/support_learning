import { JobName, QueueName } from '../../src/async/contracts/async-contracts';
import { ConsumerRegistryService } from '../../src/worker/consumer-registry.service';
import type { WorkerJobHandler } from '../../src/worker/worker-job-handler';

function handler(overrides: Partial<WorkerJobHandler> = {}): WorkerJobHandler {
  return {
    consumerName: 'foundation-test-consumer',
    queueName: QueueName.PROCESSING,
    jobName: JobName.PROCESS_DOCUMENT_VERSION,
    contractVersion: 1,
    apply: () => Promise.resolve(undefined),
    ...overrides,
  };
}

describe('ConsumerRegistryService', () => {
  it('registers a stable handler by jobName and contractVersion', () => {
    const registered = handler();
    const registry = new ConsumerRegistryService([registered]);
    registry.onModuleInit();
    expect(registry.resolve(JobName.PROCESS_DOCUMENT_VERSION, 1)).toBe(registered);
    expect(registry.queueNames()).toEqual([QueueName.PROCESSING]);
  });

  it('fails startup for duplicate handler contracts', () => {
    const registry = new ConsumerRegistryService([handler(), handler({ consumerName: 'second-consumer' })]);
    expect(() => registry.onModuleInit()).toThrow('Duplicate worker handler');
  });

  it('rejects unstable consumer names and missing handler versions', () => {
    const invalid = new ConsumerRegistryService([handler({ consumerName: 'bad consumer name' })]);
    expect(() => invalid.onModuleInit()).toThrow('consumerName');

    const registry = new ConsumerRegistryService([handler()]);
    registry.onModuleInit();
    expect(() => registry.resolve(JobName.PROCESS_DOCUMENT_VERSION, 2)).toThrow('No worker handler');
  });
});
