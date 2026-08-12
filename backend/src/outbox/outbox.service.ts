import { Injectable } from '@nestjs/common';
import { Prisma, type OutboxEvent } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import { OUTBOX_EVENT_SCHEMA_VERSION } from '../async/contracts/async-contracts';

export interface AppendOutboxEventInput {
  aggregateType: string;
  aggregateId: string;
  eventType: string;
  schemaVersion?: number;
  payload: Record<string, unknown>;
}

@Injectable()
export class OutboxService {
  append(tx: Prisma.TransactionClient, input: AppendOutboxEventInput): Promise<OutboxEvent> {
    const id = randomUUID();
    return tx.outboxEvent.create({
      data: {
        id,
        aggregateType: input.aggregateType,
        aggregateId: input.aggregateId,
        eventType: input.eventType,
        schemaVersion: input.schemaVersion ?? OUTBOX_EVENT_SCHEMA_VERSION,
        payload: { eventId: id, ...input.payload },
      },
    });
  }
}
