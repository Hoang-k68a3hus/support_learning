import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { createHash, randomUUID } from 'node:crypto';
import { AsyncContractError } from '../async/contracts/async-contract.error';

export interface PersistDeadLetterInput {
  eventId: string;
  jobName: string;
  queueName: string;
  contractVersion: number;
  errorCode: string;
  errorMessageRedacted: string;
  attempts: number;
  rawEnvelope: unknown;
  error: Error;
}

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

function stableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => stableJsonValue(item));
  if (value !== null && typeof value === 'object') {
    const input = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(input).sort().map((key) => [key, stableJsonValue(input[key])]));
  }
  if (typeof value === 'bigint') return value.toString();
  return value;
}

export function hashDeadLetterPayload(value: unknown): string | undefined {
  try {
    const serialized = JSON.stringify(stableJsonValue(value));
    return serialized === undefined ? undefined : sha256(serialized);
  } catch {
    return undefined;
  }
}

export function fingerprintDeadLetterError(error: Error): string {
  return sha256(error.stack ?? `${error.name}:${error.message}`);
}

@Injectable()
export class DeadLetterService {
  constructor(private readonly prisma: import('../database/prisma.service').PrismaService) {}

  async persistActive(input: PersistDeadLetterInput): Promise<string> {
    return this.prisma.$transaction(async (tx) => {
      const event = await tx.outboxEvent.findUnique({
        where: { id: input.eventId },
        select: { id: true },
      });
      if (!event) {
        throw new AsyncContractError(
          'DEAD_LETTER_EVENT_NOT_FOUND',
          `Cannot create dead letter for missing outbox event: ${input.eventId}`,
        );
      }

      const id = randomUUID();
      const payloadHash = hashDeadLetterPayload(input.rawEnvelope) ?? null;
      const stackFingerprint = fingerprintDeadLetterError(input.error);
      const rows = await tx.$queryRaw<Array<{ id: string }>>(Prisma.sql`
        INSERT INTO "dead_letter_records" (
          "id",
          "event_id",
          "job_name",
          "queue_name",
          "contract_version",
          "error_code",
          "error_message_redacted",
          "stack_fingerprint",
          "payload_hash",
          "attempts"
        )
        VALUES (
          ${id}::uuid,
          ${input.eventId}::uuid,
          ${input.jobName},
          ${input.queueName},
          ${input.contractVersion},
          ${input.errorCode},
          ${input.errorMessageRedacted},
          ${stackFingerprint},
          ${payloadHash},
          ${input.attempts}
        )
        ON CONFLICT ("event_id", "job_name") WHERE "resolved_at" IS NULL
        DO UPDATE SET
          "queue_name" = EXCLUDED."queue_name",
          "contract_version" = EXCLUDED."contract_version",
          "error_code" = EXCLUDED."error_code",
          "error_message_redacted" = EXCLUDED."error_message_redacted",
          "stack_fingerprint" = EXCLUDED."stack_fingerprint",
          "payload_hash" = EXCLUDED."payload_hash",
          "attempts" = GREATEST("dead_letter_records"."attempts", EXCLUDED."attempts"),
          "failed_at" = CURRENT_TIMESTAMP
        RETURNING "id"
      `);
      const row = rows[0];
      if (!row) {
        throw new Error(`Dead letter upsert returned no row for event ${input.eventId}`);
      }
      return row.id;
    });
  }

  async resolveAfterSuccessfulConsumption(eventId: string, jobName: string): Promise<number> {
    const result = await this.prisma.deadLetterRecord.updateMany({
      where: { eventId, jobName, resolvedAt: null },
      data: { resolvedAt: new Date() },
    });
    return result.count;
  }
}
