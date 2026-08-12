import type { Prisma } from '@prisma/client';
import type {
  AsyncJobPayload,
  JobEnvelope,
  JobName,
  QueueName,
} from '../async/contracts/async-contracts';
import type { InboxReceiptEffectResult } from '../inbox/inbox-receipt.service';

/**
 * M4.2 handlers are deliberately PostgreSQL-transactional handlers.
 * Implementations MUST NOT perform Redis, MinIO, AI, HTTP, or other network I/O
 * inside apply(). External-effect workflows need an explicit durable state-machine
 * boundary and are added with their owning business milestone.
 */
export interface WorkerJobHandler<TPayload extends AsyncJobPayload = AsyncJobPayload> {
  readonly consumerName: string;
  readonly queueName: QueueName;
  readonly jobName: JobName;
  readonly contractVersion: number;

  apply(
    envelope: JobEnvelope<TPayload>,
    tx: Prisma.TransactionClient,
  ): Promise<InboxReceiptEffectResult | void>;
}

export const WORKER_JOB_HANDLERS = Symbol('WORKER_JOB_HANDLERS');
