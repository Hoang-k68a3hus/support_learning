import { AsyncContractError } from '../../src/async/contracts/async-contract.error';
import { classifyJobFailure } from '../../src/worker/job-failure-classifier';
import { RetryableJobError, StaleJobError, TerminalJobError } from '../../src/worker/job-errors';

describe('classifyJobFailure', () => {
  it('preserves explicit retryable, terminal and stale failure categories', () => {
    expect(classifyJobFailure(new RetryableJobError('TEMP_DOWNSTREAM', 'Dependency unavailable'))).toMatchObject({
      kind: 'RETRYABLE',
      code: 'TEMP_DOWNSTREAM',
      messageRedacted: 'Dependency unavailable',
    });
    expect(classifyJobFailure(new TerminalJobError('BAD_STATE', 'State is invalid'))).toMatchObject({
      kind: 'TERMINAL',
      code: 'BAD_STATE',
      messageRedacted: 'State is invalid',
    });
    expect(classifyJobFailure(new StaleJobError('OBSOLETE_TARGET', 'Target is obsolete'))).toMatchObject({
      kind: 'STALE',
      code: 'OBSOLETE_TARGET',
      messageRedacted: 'Target is obsolete',
    });
  });

  it('treats async contract violations as terminal without persisting their detailed message', () => {
    const failure = classifyJobFailure(
      new AsyncContractError('WORKER_ENVELOPE_INVALID', 'secret-bearing malformed payload detail'),
    );
    expect(failure).toMatchObject({
      kind: 'TERMINAL',
      code: 'WORKER_ENVELOPE_INVALID',
      messageRedacted: 'Async job contract validation failed',
    });
    expect(failure.messageRedacted).not.toContain('secret-bearing');
  });

  it('fails closed for unclassified errors instead of blindly retrying them', () => {
    expect(classifyJobFailure(new Error('arbitrary implementation bug'))).toMatchObject({
      kind: 'TERMINAL',
      code: 'WORKER_UNCLASSIFIED_ERROR',
      messageRedacted: 'Unclassified worker failure requires explicit error typing',
    });
  });
});
