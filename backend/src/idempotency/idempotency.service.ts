import { BadRequestException, Injectable } from '@nestjs/common';
import { Prisma, type IdempotencyRecord } from '@prisma/client';
import { createHash } from 'node:crypto';
import { AppConfigService } from '../config/app-config.service';
import { DomainHttpException } from '../common/errors/domain-http.exception';

function canonicalize(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('CanonicalHashV1 does not accept non-finite numbers');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => canonicalize(item)).join(',')}]`;
  if (typeof value === 'object') {
    const object = value as Record<string, unknown>;
    const keys = Object.keys(object).sort();
    return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalize(object[key])}`).join(',')}}`;
  }
  throw new TypeError(`CanonicalHashV1 does not accept ${typeof value}`);
}

@Injectable()
export class IdempotencyService {
  constructor(private readonly config: AppConfigService) {}

  validateKey(raw: string | undefined): string {
    const key = raw?.trim();
    if (!key) throw new BadRequestException('Idempotency-Key header is required');
    if (key.length > 200) throw new BadRequestException('Idempotency-Key must be at most 200 characters');
    return key;
  }

  canonicalHashV1(value: unknown): string {
    return `v1:${createHash('sha256').update(canonicalize(value), 'utf8').digest('hex')}`;
  }

  async lockAndFind(
    tx: Prisma.TransactionClient,
    userId: string,
    scope: string,
    key: string,
    requestHash: string,
    now = new Date(),
  ): Promise<IdempotencyRecord | null> {
    const lockKey = `${userId}:${scope}:${key}`;
    await tx.$queryRaw`SELECT pg_advisory_xact_lock(hashtextextended(${lockKey}, 0))`;
    await tx.idempotencyRecord.deleteMany({ where: { userId, scope, key, expiresAt: { lte: now } } });
    const existing = await tx.idempotencyRecord.findUnique({ where: { userId_scope_key: { userId, scope, key } } });
    if (!existing) return null;
    if (existing.requestHash !== requestHash) {
      throw new DomainHttpException(409, 'IDEMPOTENCY_CONFLICT', 'Idempotency-Key was already used with a different request');
    }
    return existing;
  }

  createRecord(
    tx: Prisma.TransactionClient,
    input: {
      userId: string;
      scope: string;
      key: string;
      requestHash: string;
      responseStatus: number;
      responseBody: Prisma.InputJsonValue;
      now?: Date;
    },
  ): Promise<IdempotencyRecord> {
    const now = input.now ?? new Date();
    return tx.idempotencyRecord.create({
      data: {
        userId: input.userId,
        scope: input.scope,
        key: input.key,
        requestHash: input.requestHash,
        responseStatus: input.responseStatus,
        responseBody: input.responseBody,
        createdAt: now,
        expiresAt: new Date(now.getTime() + this.config.idempotencyTtlSeconds * 1000),
      },
    });
  }
}
