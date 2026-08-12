import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { PrismaService } from '../../database/prisma.service';

export interface ClaimedOutboxEvent {
  id: string;
  aggregateType: string;
  aggregateId: string;
  eventType: string;
  schemaVersion: number;
  payload: Prisma.JsonValue;
  createdAt: Date;
  availableAt: Date;
  attempts: number;
  claimOwner: string;
  claimExpiresAt: Date;
}

@Injectable()
export class OutboxRelayRepository {
  constructor(private readonly prisma: PrismaService) {}

  async claimBatch(input: {
    instanceId: string;
    batchSize: number;
    claimLeaseMs: number;
    maxPublishAttempts: number;
  }): Promise<ClaimedOutboxEvent[]> {
    return this.prisma.$transaction(async (tx) => {
      await tx.$executeRaw(Prisma.sql`
        UPDATE "outbox_events"
        SET
          "status" = 'FAILED'::"OutboxStatus",
          "claim_owner" = NULL,
          "claim_expires_at" = NULL,
          "last_error_code" = 'OUTBOX_PUBLISH_ATTEMPTS_EXHAUSTED',
          "last_error_at" = CURRENT_TIMESTAMP
        WHERE "attempts" >= ${input.maxPublishAttempts}
          AND (
            ("status" = 'PENDING'::"OutboxStatus" AND "available_at" <= CURRENT_TIMESTAMP)
            OR
            ("status" = 'PUBLISHING'::"OutboxStatus" AND "claim_expires_at" <= CURRENT_TIMESTAMP)
          )
      `);

      return tx.$queryRaw<ClaimedOutboxEvent[]>(Prisma.sql`
        WITH candidates AS (
          SELECT "id"
          FROM "outbox_events"
          WHERE "attempts" < ${input.maxPublishAttempts}
            AND (
              ("status" = 'PENDING'::"OutboxStatus" AND "available_at" <= CURRENT_TIMESTAMP)
              OR
              ("status" = 'PUBLISHING'::"OutboxStatus" AND "claim_expires_at" <= CURRENT_TIMESTAMP)
            )
          ORDER BY "available_at" ASC, "created_at" ASC
          FOR UPDATE SKIP LOCKED
          LIMIT ${input.batchSize}
        )
        UPDATE "outbox_events" AS event
        SET
          "status" = 'PUBLISHING'::"OutboxStatus",
          "claim_owner" = ${input.instanceId},
          "claim_expires_at" = CURRENT_TIMESTAMP + (${input.claimLeaseMs} * INTERVAL '1 millisecond'),
          "attempts" = event."attempts" + 1
        FROM candidates
        WHERE event."id" = candidates."id"
        RETURNING
          event."id",
          event."aggregate_type" AS "aggregateType",
          event."aggregate_id" AS "aggregateId",
          event."event_type" AS "eventType",
          event."schema_version" AS "schemaVersion",
          event."payload",
          event."created_at" AS "createdAt",
          event."available_at" AS "availableAt",
          event."attempts",
          event."claim_owner" AS "claimOwner",
          event."claim_expires_at" AS "claimExpiresAt"
      `);
    });
  }

  async markPublished(eventId: string, instanceId: string): Promise<boolean> {
    const updated = await this.prisma.$executeRaw(Prisma.sql`
      UPDATE "outbox_events"
      SET
        "status" = 'PUBLISHED'::"OutboxStatus",
        "published_at" = CURRENT_TIMESTAMP,
        "claim_owner" = NULL,
        "claim_expires_at" = NULL
      WHERE "id" = ${eventId}::uuid
        AND "status" = 'PUBLISHING'::"OutboxStatus"
        AND "claim_owner" = ${instanceId}
    `);
    return updated === 1;
  }

  async rescheduleFailure(input: {
    eventId: string;
    instanceId: string;
    errorCode: string;
    delayMs: number;
  }): Promise<boolean> {
    const updated = await this.prisma.$executeRaw(Prisma.sql`
      UPDATE "outbox_events"
      SET
        "status" = 'PENDING'::"OutboxStatus",
        "available_at" = CURRENT_TIMESTAMP + (${input.delayMs} * INTERVAL '1 millisecond'),
        "claim_owner" = NULL,
        "claim_expires_at" = NULL,
        "last_error_code" = ${input.errorCode},
        "last_error_at" = CURRENT_TIMESTAMP
      WHERE "id" = ${input.eventId}::uuid
        AND "status" = 'PUBLISHING'::"OutboxStatus"
        AND "claim_owner" = ${input.instanceId}
    `);
    return updated === 1;
  }

  async markFailed(input: { eventId: string; instanceId: string; errorCode: string }): Promise<boolean> {
    const updated = await this.prisma.$executeRaw(Prisma.sql`
      UPDATE "outbox_events"
      SET
        "status" = 'FAILED'::"OutboxStatus",
        "claim_owner" = NULL,
        "claim_expires_at" = NULL,
        "last_error_code" = ${input.errorCode},
        "last_error_at" = CURRENT_TIMESTAMP
      WHERE "id" = ${input.eventId}::uuid
        AND "status" = 'PUBLISHING'::"OutboxStatus"
        AND "claim_owner" = ${input.instanceId}
    `);
    return updated === 1;
  }
}
