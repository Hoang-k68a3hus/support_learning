import { parseDurationSeconds, validateEnvironment } from '../../src/config/env.validation';

const validEnv = (): Record<string, unknown> => ({
  NODE_ENV: 'test',
  PORT: '3001',
  DATABASE_URL: 'postgresql://user:password@localhost:5432/support_learning_test',
  JWT_ACCESS_SECRET: 'a'.repeat(32),
  JWT_ACCESS_TTL: '15m',
  JWT_REFRESH_SECRET: 'b'.repeat(32),
  JWT_REFRESH_TTL: '7d',
  CORS_ORIGIN: 'http://localhost:3000',
  STORAGE_ENDPOINT: 'http://localhost:9000',
  STORAGE_ACCESS_KEY: 'test-access',
  STORAGE_SECRET_KEY: 'test-secret',
  STORAGE_BUCKET: 'support-learning-test',
  STORAGE_UPLOAD_TTL: '15m',
  STORAGE_MAX_UPLOAD_BYTES: '104857600',
  STORAGE_ALLOWED_MEDIA_TYPES: 'application/pdf,text/plain',
  IDEMPOTENCY_TTL: '24h',
  REDIS_URL: 'redis://localhost:6379/0',
  BULLMQ_PREFIX: 'support-learning:test',
  OUTBOX_RELAY_INSTANCE_ID: 'test-relay-1',
  OUTBOX_RELAY_POLL_INTERVAL_MS: '100',
  OUTBOX_RELAY_BATCH_SIZE: '20',
  OUTBOX_RELAY_CLAIM_LEASE_MS: '5000',
  OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS: '4',
  OUTBOX_RELAY_BACKOFF_BASE_MS: '100',
  OUTBOX_RELAY_BACKOFF_MAX_MS: '1000',
  WORKER_INSTANCE_ID: 'test-worker-1',
  WORKER_PROCESSING_CONCURRENCY: '4',
  WORKER_LEARNING_CONCURRENCY: '2',
  WORKER_MAINTENANCE_CONCURRENCY: '1',
  WORKER_SHUTDOWN_GRACE_MS: '5000',
});

describe('validateEnvironment', () => {
  it('accepts valid configuration and parses TTLs, storage, Redis, relay and worker settings', () => {
    const result = validateEnvironment(validEnv());
    expect(result.PORT).toBe(3001);
    expect(result.JWT_ACCESS_TTL_SECONDS).toBe(900);
    expect(result.JWT_REFRESH_TTL_SECONDS).toBe(604800);
    expect(result.STORAGE_UPLOAD_TTL_SECONDS).toBe(900);
    expect(result.STORAGE_MAX_UPLOAD_BYTES).toBe(104857600);
    expect(result.STORAGE_ALLOWED_MEDIA_TYPES).toEqual(['application/pdf', 'text/plain']);
    expect(result.IDEMPOTENCY_TTL_SECONDS).toBe(86400);
    expect(result.REDIS_URL).toBe('redis://localhost:6379/0');
    expect(result.OUTBOX_RELAY_BATCH_SIZE).toBe(20);
    expect(result.OUTBOX_RELAY_CLAIM_LEASE_MS).toBe(5000);
    expect(result.WORKER_INSTANCE_ID).toBe('test-worker-1');
    expect(result.WORKER_PROCESSING_CONCURRENCY).toBe(4);
    expect(result.WORKER_SHUTDOWN_GRACE_MS).toBe(5000);
  });

  it('rejects an invalid port', () => {
    const env = validEnv();
    env.PORT = '70000';
    expect(() => validateEnvironment(env)).toThrow('PORT');
  });

  it('rejects a missing DATABASE_URL', () => {
    const env = validEnv();
    delete env.DATABASE_URL;
    expect(() => validateEnvironment(env)).toThrow('DATABASE_URL');
  });

  it('rejects a missing JWT secret', () => {
    const env = validEnv();
    delete env.JWT_ACCESS_SECRET;
    expect(() => validateEnvironment(env)).toThrow('JWT_ACCESS_SECRET');
  });

  it('rejects placeholder JWT secrets even when they are long enough', () => {
    const accessPlaceholder = validEnv();
    accessPlaceholder.JWT_ACCESS_SECRET = 'REPLACE_ME_WITH_RANDOM_ACCESS_SECRET_AT_LEAST_32_CHARS';
    expect(() => validateEnvironment(accessPlaceholder)).toThrow('placeholder');

    const refreshPlaceholder = validEnv();
    refreshPlaceholder.JWT_REFRESH_SECRET = 'CHANGE_ME_TO_A_DIFFERENT_REFRESH_SECRET_VALUE_123456';
    expect(() => validateEnvironment(refreshPlaceholder)).toThrow('placeholder');
  });

  it('rejects invalid TTL syntax and access TTL >= refresh TTL', () => {
    expect(() => parseDurationSeconds('tomorrow', 'TTL')).toThrow('TTL');
    const env = validEnv();
    env.JWT_ACCESS_TTL = '8d';
    expect(() => validateEnvironment(env)).toThrow('shorter');
  });

  it('rejects wildcard CORS and identical secrets', () => {
    const wildcard = validEnv();
    wildcard.CORS_ORIGIN = '*';
    expect(() => validateEnvironment(wildcard)).toThrow('explicit origins');

    const sameSecrets = validEnv();
    sameSecrets.JWT_REFRESH_SECRET = sameSecrets.JWT_ACCESS_SECRET;
    expect(() => validateEnvironment(sameSecrets)).toThrow('must be different');
  });

  it('rejects malformed storage settings', () => {
    const endpoint = validEnv();
    endpoint.STORAGE_ENDPOINT = 'http://localhost:9000/path';
    expect(() => validateEnvironment(endpoint)).toThrow('STORAGE_ENDPOINT');

    const bucket = validEnv();
    bucket.STORAGE_BUCKET = 'INVALID_BUCKET';
    expect(() => validateEnvironment(bucket)).toThrow('STORAGE_BUCKET');

    const media = validEnv();
    media.STORAGE_ALLOWED_MEDIA_TYPES = 'not-a-mime';
    expect(() => validateEnvironment(media)).toThrow('STORAGE_ALLOWED_MEDIA_TYPES');

    const size = validEnv();
    size.STORAGE_MAX_UPLOAD_BYTES = '0';
    expect(() => validateEnvironment(size)).toThrow('STORAGE_MAX_UPLOAD_BYTES');
  });

  it('rejects malformed Redis, relay and worker settings', () => {
    const redis = validEnv();
    redis.REDIS_URL = 'https://localhost:6379';
    expect(() => validateEnvironment(redis)).toThrow('REDIS_URL');

    const lease = validEnv();
    lease.OUTBOX_RELAY_CLAIM_LEASE_MS = '50';
    expect(() => validateEnvironment(lease)).toThrow('OUTBOX_RELAY_CLAIM_LEASE_MS');

    const backoff = validEnv();
    backoff.OUTBOX_RELAY_BACKOFF_BASE_MS = '2000';
    backoff.OUTBOX_RELAY_BACKOFF_MAX_MS = '1000';
    expect(() => validateEnvironment(backoff)).toThrow('BACKOFF_MAX');

    const concurrency = validEnv();
    concurrency.WORKER_PROCESSING_CONCURRENCY = '0';
    expect(() => validateEnvironment(concurrency)).toThrow('WORKER_PROCESSING_CONCURRENCY');

    const grace = validEnv();
    grace.WORKER_SHUTDOWN_GRACE_MS = '500';
    expect(() => validateEnvironment(grace)).toThrow('WORKER_SHUTDOWN_GRACE_MS');
  });
});
