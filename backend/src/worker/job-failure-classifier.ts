import { Prisma } from '@prisma/client';
import { AsyncContractError } from '../async/contracts/async-contract.error';
import { RetryableJobError, StaleJobError, TerminalJobError } from './job-errors';

export type JobFailureKind = 'RETRYABLE' | 'TERMINAL' | 'STALE';

export interface ClassifiedJobFailure {
  kind: JobFailureKind;
  code: string;
  messageRedacted: string;
  error: Error;
}

const TRANSIENT_PRISMA_CODES = new Set(['P2024', 'P2034']);

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error('Non-Error value thrown by worker handler');
}

export function classifyJobFailure(error: unknown): ClassifiedJobFailure {
  const normalized = asError(error);

  if (error instanceof StaleJobError) {
    return {
      kind: 'STALE',
      code: error.code,
      messageRedacted: error.redactedMessage,
      error: normalized,
    };
  }
  if (error instanceof RetryableJobError) {
    return {
      kind: 'RETRYABLE',
      code: error.code,
      messageRedacted: error.redactedMessage,
      error: normalized,
    };
  }
  if (error instanceof TerminalJobError) {
    return {
      kind: 'TERMINAL',
      code: error.code,
      messageRedacted: error.redactedMessage,
      error: normalized,
    };
  }
  if (error instanceof AsyncContractError) {
    return {
      kind: 'TERMINAL',
      code: error.code,
      messageRedacted: 'Async job contract validation failed',
      error: normalized,
    };
  }
  if (error instanceof Prisma.PrismaClientKnownRequestError && TRANSIENT_PRISMA_CODES.has(error.code)) {
    return {
      kind: 'RETRYABLE',
      code: `PRISMA_${error.code}`,
      messageRedacted: 'Transient PostgreSQL operation failed',
      error: normalized,
    };
  }
  if (error instanceof Prisma.PrismaClientInitializationError) {
    return {
      kind: 'RETRYABLE',
      code: 'PRISMA_CONNECTION_UNAVAILABLE',
      messageRedacted: 'PostgreSQL dependency is temporarily unavailable',
      error: normalized,
    };
  }

  return {
    kind: 'TERMINAL',
    code: 'WORKER_UNCLASSIFIED_ERROR',
    messageRedacted: 'Unclassified worker failure requires explicit error typing',
    error: normalized,
  };
}
