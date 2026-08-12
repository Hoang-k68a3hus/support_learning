import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { AsyncContractError } from '../async/contracts/async-contract.error';
import type { AsyncEventType, JobName } from '../async/contracts/async-contracts';
import { PrismaService } from '../database/prisma.service';

const RESULT_HASH_PATTERN = /^[0-9a-f]{64}$/;

export interface InboxReceiptEffectResult {
  resultHash?: string;
  metadata?: Prisma.InputJsonValue;
}

export interface InboxExecutionResult {
  deduplicated: boolean;
  receiptId: string;
}

export interface InboxReceiptExecutionInput {
  consumerName: string;
  eventId: string;
  eventType: AsyncEventType;
  aggregateType: string;
  aggregateId: string;
  jobName: JobName;
  contractVersion: number;
}

@Injectable()
export class InboxReceiptService {
  constructor(private readonly prisma: PrismaService) {}

  async executeOnce(
    input: InboxReceiptExecutionInput,
    effect: (tx: Prisma.TransactionClient) => Promise<InboxReceiptEffectResult | void>,
  ): Promise<InboxExecutionResult> {
    return this.prisma.$transaction(async (tx) => {
      const [event] = await tx.$queryRaw<
        Array<{
          id: string;
          eventType: AsyncEventType;
          aggregateType: string;
          aggregateId: string;
        }>
      >(Prisma.sql`
        SELECT
          "id",
          "event_type" AS "eventType",
          "aggregate_type" AS "aggregateType",
          "aggregate_id" AS "aggregateId"
        FROM "outbox_events"
        WHERE "id" = ${input.eventId}::uuid
        FOR UPDATE
      `);

      if (!event) {
        throw new AsyncContractError('INBOX_EVENT_NOT_FOUND', `Outbox event does not exist: ${input.eventId}`);
      }
      if (
        event.eventType !== input.eventType ||
        event.aggregateType !== input.aggregateType ||
        event.aggregateId !== input.aggregateId
      ) {
        throw new AsyncContractError(
          'INBOX_EVENT_IDENTITY_MISMATCH',
          `Job envelope does not match durable outbox event: ${input.eventId}`,
        );
      }

      const existing = await tx.inboxReceipt.findUnique({
        where: {
          consumerName_eventId_jobName: {
            consumerName: input.consumerName,
            eventId: input.eventId,
            jobName: input.jobName,
          },
        },
      });

      if (existing) {
        if (existing.contractVersion !== input.contractVersion) {
          throw new AsyncContractError(
            'INBOX_RECEIPT_CONTRACT_CONFLICT',
            `Existing receipt uses contract version ${existing.contractVersion}, received ${input.contractVersion}`,
          );
        }
        return { deduplicated: true, receiptId: existing.id };
      }

      const effectResult = await effect(tx);
      if (effectResult?.resultHash && !RESULT_HASH_PATTERN.test(effectResult.resultHash)) {
        throw new AsyncContractError('INBOX_RESULT_HASH_INVALID', 'resultHash must be a lowercase SHA-256 hex digest');
      }

      const receipt = await tx.inboxReceipt.create({
        data: {
          consumerName: input.consumerName,
          eventId: input.eventId,
          jobName: input.jobName,
          contractVersion: input.contractVersion,
          resultHash: effectResult?.resultHash,
          metadata: effectResult?.metadata,
        },
        select: { id: true },
      });

      return { deduplicated: false, receiptId: receipt.id };
    });
  }
}
