process.env.NODE_ENV = 'test';
process.env.PORT = process.env.PORT ?? '3001';
process.env.JWT_ACCESS_SECRET = process.env.JWT_ACCESS_SECRET ?? 'test-access-secret-only-32-characters-minimum';
process.env.JWT_ACCESS_TTL = process.env.JWT_ACCESS_TTL ?? '15m';
process.env.JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET ?? 'test-refresh-secret-only-32-characters-minimum-different';
process.env.JWT_REFRESH_TTL = process.env.JWT_REFRESH_TTL ?? '7d';
process.env.CORS_ORIGIN = process.env.CORS_ORIGIN ?? 'http://localhost:3000';
process.env.REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379/0';
process.env.BULLMQ_PREFIX = process.env.BULLMQ_PREFIX ?? 'support-learning:test';
process.env.OUTBOX_RELAY_INSTANCE_ID = process.env.OUTBOX_RELAY_INSTANCE_ID ?? 'test-relay-1';
process.env.OUTBOX_RELAY_POLL_INTERVAL_MS = process.env.OUTBOX_RELAY_POLL_INTERVAL_MS ?? '100';
process.env.OUTBOX_RELAY_BATCH_SIZE = process.env.OUTBOX_RELAY_BATCH_SIZE ?? '20';
process.env.OUTBOX_RELAY_CLAIM_LEASE_MS = process.env.OUTBOX_RELAY_CLAIM_LEASE_MS ?? '5000';
process.env.OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS = process.env.OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS ?? '4';
process.env.OUTBOX_RELAY_BACKOFF_BASE_MS = process.env.OUTBOX_RELAY_BACKOFF_BASE_MS ?? '100';
process.env.OUTBOX_RELAY_BACKOFF_MAX_MS = process.env.OUTBOX_RELAY_BACKOFF_MAX_MS ?? '1000';

if (!process.env.DATABASE_URL) {
  throw new Error('DATABASE_URL is required for integration/E2E tests');
}
