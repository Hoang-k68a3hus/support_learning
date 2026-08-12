export type NodeEnvironment = 'development' | 'test' | 'production';

export interface ValidatedEnvironment {
  NODE_ENV: NodeEnvironment;
  PORT: number;
  DATABASE_URL: string;
  JWT_ACCESS_SECRET: string;
  JWT_ACCESS_TTL_SECONDS: number;
  JWT_REFRESH_SECRET: string;
  JWT_REFRESH_TTL_SECONDS: number;
  CORS_ORIGINS: string[];
  STORAGE_ENDPOINT: string;
  STORAGE_ACCESS_KEY: string;
  STORAGE_SECRET_KEY: string;
  STORAGE_BUCKET: string;
  STORAGE_UPLOAD_TTL_SECONDS: number;
  STORAGE_MAX_UPLOAD_BYTES: number;
  STORAGE_ALLOWED_MEDIA_TYPES: string[];
  IDEMPOTENCY_TTL_SECONDS: number;
  REDIS_URL: string;
  BULLMQ_PREFIX: string;
  OUTBOX_RELAY_INSTANCE_ID: string;
  OUTBOX_RELAY_POLL_INTERVAL_MS: number;
  OUTBOX_RELAY_BATCH_SIZE: number;
  OUTBOX_RELAY_CLAIM_LEASE_MS: number;
  OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS: number;
  OUTBOX_RELAY_BACKOFF_BASE_MS: number;
  OUTBOX_RELAY_BACKOFF_MAX_MS: number;
}

const SECRET_MIN_LENGTH = 32;
const TTL_PATTERN = /^(\d+)(s|m|h|d)?$/;
const BUCKET_PATTERN = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const CONTROLLED_NAME_PATTERN = /^[A-Za-z0-9._:-]+$/;
const UNSAFE_SECRET_PATTERNS = [
  /REPLACE[_\s-]*ME/i,
  /REPLACE[_\s-]*WITH/i,
  /CHANGE[_\s-]*ME/i,
  /PLACEHOLDER/i,
  /GENERATE[_\s-]*RANDOM/i,
];
type DurationUnit = 's' | 'm' | 'h' | 'd';

function requireString(env: Record<string, unknown>, key: string): string {
  const value = env[key];
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new Error(`Environment variable ${key} is required`);
  }
  return value.trim();
}

function validateJwtSecret(value: string, key: string): void {
  if (value.length < SECRET_MIN_LENGTH) {
    throw new Error(`${key} must be at least ${SECRET_MIN_LENGTH} characters`);
  }
  if (UNSAFE_SECRET_PATTERNS.some((pattern) => pattern.test(value))) {
    throw new Error(`${key} must not use a placeholder or example value`);
  }
}

export function parseDurationSeconds(value: string, key: string): number {
  const match = TTL_PATTERN.exec(value.trim());
  const amountText = match?.[1];
  if (!match || !amountText) {
    throw new Error(`${key} must be a positive integer optionally suffixed by s, m, h, or d`);
  }

  const amount = Number(amountText);
  if (!Number.isSafeInteger(amount) || amount <= 0) {
    throw new Error(`${key} must be greater than zero`);
  }

  const unit = (match[2] ?? 's') as DurationUnit;
  const multiplier = unit === 'd' ? 86400 : unit === 'h' ? 3600 : unit === 'm' ? 60 : 1;
  const seconds = amount * multiplier;
  if (!Number.isSafeInteger(seconds)) {
    throw new Error(`${key} is too large`);
  }
  return seconds;
}

function parsePositiveInteger(value: string, key: string): number {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${key} must be a positive safe integer`);
  }
  return parsed;
}

function parseBoundedPositiveInteger(value: string, key: string, min: number, max: number): number {
  const parsed = parsePositiveInteger(value, key);
  if (parsed < min || parsed > max) {
    throw new Error(`${key} must be between ${min} and ${max}`);
  }
  return parsed;
}

function parseCorsOrigins(value: string): string[] {
  const origins = value
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);

  if (origins.length === 0 || origins.includes('*')) {
    throw new Error('CORS_ORIGIN must contain one or more explicit origins and cannot contain *');
  }

  for (const origin of origins) {
    let parsed: URL;
    try {
      parsed = new URL(origin);
    } catch {
      throw new Error(`CORS_ORIGIN contains an invalid URL: ${origin}`);
    }
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.origin !== origin) {
      throw new Error(`CORS_ORIGIN must contain origins only, without paths: ${origin}`);
    }
  }

  return [...new Set(origins)];
}

function parseStorageEndpoint(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('STORAGE_ENDPOINT must be a valid HTTP(S) URL');
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('STORAGE_ENDPOINT must be an HTTP(S) origin without path, query, or fragment');
  }
  return parsed.origin;
}

function parseRedisUrl(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('REDIS_URL must be a valid Redis URL');
  }
  if (!['redis:', 'rediss:'].includes(parsed.protocol) || parsed.hash) {
    throw new Error('REDIS_URL must use redis:// or rediss:// and cannot contain a fragment');
  }
  if (!parsed.hostname) throw new Error('REDIS_URL must include a host');
  if (parsed.pathname !== '/' && !/^\/\d+$/.test(parsed.pathname)) {
    throw new Error('REDIS_URL path may only select a numeric Redis database');
  }
  return value;
}

function parseControlledName(value: string, key: string, maxLength: number): string {
  if (value.length > maxLength || !CONTROLLED_NAME_PATTERN.test(value)) {
    throw new Error(`${key} must be at most ${maxLength} characters using letters, numbers, dot, underscore, colon, or dash`);
  }
  return value;
}

function parseAllowedMediaTypes(value: string): string[] {
  const mediaTypes = value
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (mediaTypes.length === 0 || mediaTypes.some((item) => !item.includes('/'))) {
    throw new Error('STORAGE_ALLOWED_MEDIA_TYPES must contain one or more MIME types');
  }
  return [...new Set(mediaTypes)];
}

function isNodeEnvironment(value: string): value is NodeEnvironment {
  return value === 'development' || value === 'test' || value === 'production';
}

export function validateEnvironment(env: Record<string, unknown>): ValidatedEnvironment {
  const nodeEnv = requireString(env, 'NODE_ENV');
  if (!isNodeEnvironment(nodeEnv)) {
    throw new Error('NODE_ENV must be development, test, or production');
  }

  const portValue = requireString(env, 'PORT');
  const port = Number(portValue);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer between 1 and 65535');
  }

  const databaseUrl = requireString(env, 'DATABASE_URL');
  let databaseProtocol: string;
  try {
    databaseProtocol = new URL(databaseUrl).protocol;
  } catch {
    throw new Error('DATABASE_URL must be a valid PostgreSQL URL');
  }
  if (databaseProtocol !== 'postgres:' && databaseProtocol !== 'postgresql:') {
    throw new Error('DATABASE_URL must use postgres:// or postgresql://');
  }

  const accessSecret = requireString(env, 'JWT_ACCESS_SECRET');
  const refreshSecret = requireString(env, 'JWT_REFRESH_SECRET');
  validateJwtSecret(accessSecret, 'JWT_ACCESS_SECRET');
  validateJwtSecret(refreshSecret, 'JWT_REFRESH_SECRET');
  if (accessSecret === refreshSecret) {
    throw new Error('JWT_ACCESS_SECRET and JWT_REFRESH_SECRET must be different');
  }

  const accessTtl = parseDurationSeconds(requireString(env, 'JWT_ACCESS_TTL'), 'JWT_ACCESS_TTL');
  const refreshTtl = parseDurationSeconds(requireString(env, 'JWT_REFRESH_TTL'), 'JWT_REFRESH_TTL');
  if (accessTtl >= refreshTtl) {
    throw new Error('JWT_ACCESS_TTL must be shorter than JWT_REFRESH_TTL');
  }

  const storageBucket = requireString(env, 'STORAGE_BUCKET');
  if (!BUCKET_PATTERN.test(storageBucket)) {
    throw new Error('STORAGE_BUCKET must be a valid 3-63 character S3 bucket name');
  }

  const outboxRelayPollIntervalMs = parseBoundedPositiveInteger(
    requireString(env, 'OUTBOX_RELAY_POLL_INTERVAL_MS'),
    'OUTBOX_RELAY_POLL_INTERVAL_MS',
    50,
    60000,
  );
  const outboxRelayClaimLeaseMs = parseBoundedPositiveInteger(
    requireString(env, 'OUTBOX_RELAY_CLAIM_LEASE_MS'),
    'OUTBOX_RELAY_CLAIM_LEASE_MS',
    1000,
    600000,
  );
  if (outboxRelayClaimLeaseMs <= outboxRelayPollIntervalMs) {
    throw new Error('OUTBOX_RELAY_CLAIM_LEASE_MS must be greater than OUTBOX_RELAY_POLL_INTERVAL_MS');
  }

  const outboxRelayBackoffBaseMs = parseBoundedPositiveInteger(
    requireString(env, 'OUTBOX_RELAY_BACKOFF_BASE_MS'),
    'OUTBOX_RELAY_BACKOFF_BASE_MS',
    100,
    600000,
  );
  const outboxRelayBackoffMaxMs = parseBoundedPositiveInteger(
    requireString(env, 'OUTBOX_RELAY_BACKOFF_MAX_MS'),
    'OUTBOX_RELAY_BACKOFF_MAX_MS',
    100,
    86400000,
  );
  if (outboxRelayBackoffMaxMs < outboxRelayBackoffBaseMs) {
    throw new Error('OUTBOX_RELAY_BACKOFF_MAX_MS must be >= OUTBOX_RELAY_BACKOFF_BASE_MS');
  }

  return {
    NODE_ENV: nodeEnv,
    PORT: port,
    DATABASE_URL: databaseUrl,
    JWT_ACCESS_SECRET: accessSecret,
    JWT_ACCESS_TTL_SECONDS: accessTtl,
    JWT_REFRESH_SECRET: refreshSecret,
    JWT_REFRESH_TTL_SECONDS: refreshTtl,
    CORS_ORIGINS: parseCorsOrigins(requireString(env, 'CORS_ORIGIN')),
    STORAGE_ENDPOINT: parseStorageEndpoint(requireString(env, 'STORAGE_ENDPOINT')),
    STORAGE_ACCESS_KEY: requireString(env, 'STORAGE_ACCESS_KEY'),
    STORAGE_SECRET_KEY: requireString(env, 'STORAGE_SECRET_KEY'),
    STORAGE_BUCKET: storageBucket,
    STORAGE_UPLOAD_TTL_SECONDS: parseDurationSeconds(requireString(env, 'STORAGE_UPLOAD_TTL'), 'STORAGE_UPLOAD_TTL'),
    STORAGE_MAX_UPLOAD_BYTES: parsePositiveInteger(requireString(env, 'STORAGE_MAX_UPLOAD_BYTES'), 'STORAGE_MAX_UPLOAD_BYTES'),
    STORAGE_ALLOWED_MEDIA_TYPES: parseAllowedMediaTypes(requireString(env, 'STORAGE_ALLOWED_MEDIA_TYPES')),
    IDEMPOTENCY_TTL_SECONDS: parseDurationSeconds(requireString(env, 'IDEMPOTENCY_TTL'), 'IDEMPOTENCY_TTL'),
    REDIS_URL: parseRedisUrl(requireString(env, 'REDIS_URL')),
    BULLMQ_PREFIX: parseControlledName(requireString(env, 'BULLMQ_PREFIX'), 'BULLMQ_PREFIX', 120),
    OUTBOX_RELAY_INSTANCE_ID: parseControlledName(
      requireString(env, 'OUTBOX_RELAY_INSTANCE_ID'),
      'OUTBOX_RELAY_INSTANCE_ID',
      160,
    ),
    OUTBOX_RELAY_POLL_INTERVAL_MS: outboxRelayPollIntervalMs,
    OUTBOX_RELAY_BATCH_SIZE: parseBoundedPositiveInteger(
      requireString(env, 'OUTBOX_RELAY_BATCH_SIZE'),
      'OUTBOX_RELAY_BATCH_SIZE',
      1,
      1000,
    ),
    OUTBOX_RELAY_CLAIM_LEASE_MS: outboxRelayClaimLeaseMs,
    OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS: parseBoundedPositiveInteger(
      requireString(env, 'OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS'),
      'OUTBOX_RELAY_MAX_PUBLISH_ATTEMPTS',
      1,
      100,
    ),
    OUTBOX_RELAY_BACKOFF_BASE_MS: outboxRelayBackoffBaseMs,
    OUTBOX_RELAY_BACKOFF_MAX_MS: outboxRelayBackoffMaxMs,
  };
}
