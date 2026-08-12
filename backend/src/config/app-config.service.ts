import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { NodeEnvironment, ValidatedEnvironment } from './env.validation';

@Injectable()
export class AppConfigService {
  constructor(private readonly config: ConfigService<ValidatedEnvironment, true>) {}

  get nodeEnv(): NodeEnvironment {
    return this.config.get('NODE_ENV', { infer: true });
  }

  get port(): number {
    return this.config.get('PORT', { infer: true });
  }

  get databaseUrl(): string {
    return this.config.get('DATABASE_URL', { infer: true });
  }

  get jwtAccessSecret(): string {
    return this.config.get('JWT_ACCESS_SECRET', { infer: true });
  }

  get jwtAccessTtlSeconds(): number {
    return this.config.get('JWT_ACCESS_TTL_SECONDS', { infer: true });
  }

  get jwtRefreshSecret(): string {
    return this.config.get('JWT_REFRESH_SECRET', { infer: true });
  }

  get jwtRefreshTtlSeconds(): number {
    return this.config.get('JWT_REFRESH_TTL_SECONDS', { infer: true });
  }

  get corsOrigins(): string[] {
    return this.config.get('CORS_ORIGINS', { infer: true });
  }

  get storageEndpoint(): string {
    return this.config.get('STORAGE_ENDPOINT', { infer: true });
  }

  get storageAccessKey(): string {
    return this.config.get('STORAGE_ACCESS_KEY', { infer: true });
  }

  get storageSecretKey(): string {
    return this.config.get('STORAGE_SECRET_KEY', { infer: true });
  }

  get storageBucket(): string {
    return this.config.get('STORAGE_BUCKET', { infer: true });
  }

  get storageUploadTtlSeconds(): number {
    return this.config.get('STORAGE_UPLOAD_TTL_SECONDS', { infer: true });
  }

  get storageMaxUploadBytes(): number {
    return this.config.get('STORAGE_MAX_UPLOAD_BYTES', { infer: true });
  }

  get storageAllowedMediaTypes(): string[] {
    return this.config.get('STORAGE_ALLOWED_MEDIA_TYPES', { infer: true });
  }

  get idempotencyTtlSeconds(): number {
    return this.config.get('IDEMPOTENCY_TTL_SECONDS', { infer: true });
  }

  get redisUrl(): string {
    return this.config.get('REDIS_URL', { infer: true });
  }

  get bullMqPrefix(): string {
    return this.config.get('BULLMQ_PREFIX', { infer: true });
  }

  get outboxRelayInstanceId(): string {
    return this.config.get('OUTBOX_RELAY_INSTANCE_ID', { infer: true });
  }

  get outboxRelayPollIntervalMs(): number {
    return this.config.get('OUTBOX_RELAY_POLL_INTERVAL_MS', { infer: true });
  }

  get outboxRelayBatchSize(): number {
    return this.config.get('OUTBOX_RELAY_BATCH_SIZE', { infer: true });
  }

  get outboxRelayClaimLeaseMs(): number {
    return this.config.get('OUTBOX_RELAY_CLAIM_LEASE_MS', { infer: true });
  }

  get outboxRelayMaxPublishAttempts(): number {
    return this.config.get('OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS', { infer: true });
  }

  get outboxRelayBackoffBaseMs(): number {
    return this.config.get('OUTBOX_RELAY_BACKOFF_BASE_MS', { infer: true });
  }

  get outboxRelayBackoffMaxMs(): number {
    return this.config.get('OUTBOX_RELAY_BACKOFF_MAX_MS', { infer: true });
  }

  get isProduction(): boolean {
    return this.nodeEnv === 'production';
  }
}
