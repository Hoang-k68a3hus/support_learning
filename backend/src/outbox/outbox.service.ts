import { Injectable } from '@nestjs/common';
import { Prisma, type OutboxEvent } from '@prisma/client';
import { randomUUID } from 'node:crypto';

export interface AppendOutboxEventInput {
  aggregateType: string;
  aggregateId: string;
  eventType: string;
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
        payload: { eventId: id, ...input.payload } as Prisma.InputJsonValue,
      },
    });
  }
}
