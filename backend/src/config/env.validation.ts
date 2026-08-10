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
}

const SECRET_MIN_LENGTH = 32;
const TTL_PATTERN = /^(\d+)(s|m|h|d)?$/;
type DurationUnit = 's' | 'm' | 'h' | 'd';

function requireString(env: Record<string, unknown>, key: string): string {
  const value = env[key];
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new Error(`Environment variable ${key} is required`);
  }
  return value.trim();
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
  if (accessSecret.length < SECRET_MIN_LENGTH || refreshSecret.length < SECRET_MIN_LENGTH) {
    throw new Error(`JWT secrets must be at least ${SECRET_MIN_LENGTH} characters`);
  }
  if (accessSecret === refreshSecret) {
    throw new Error('JWT_ACCESS_SECRET and JWT_REFRESH_SECRET must be different');
  }

  const accessTtl = parseDurationSeconds(requireString(env, 'JWT_ACCESS_TTL'), 'JWT_ACCESS_TTL');
  const refreshTtl = parseDurationSeconds(requireString(env, 'JWT_REFRESH_TTL'), 'JWT_REFRESH_TTL');
  if (accessTtl >= refreshTtl) {
    throw new Error('JWT_ACCESS_TTL must be shorter than JWT_REFRESH_TTL');
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
  };
}
