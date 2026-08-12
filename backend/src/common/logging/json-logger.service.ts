import { Injectable, type LoggerService } from '@nestjs/common';

const REDACTED_KEYS = new Set([
  'password',
  'passwordhash',
  'password_hash',
  'refreshtoken',
  'refresh_token',
  'accesstoken',
  'access_token',
  'authorization',
  'cookie',
  'set-cookie',
  'database_url',
  'databaseurl',
  'redis_url',
  'redisurl',
  'storage_access_key',
  'storage_secret_key',
  'jwt_access_secret',
  'jwt_refresh_secret',
]);

const REDACTIONS: RegExp[] = [
  /Bearer\s+[A-Za-z0-9._~-]+/gi,
  /postgres(?:ql)?:\/\/[^\s@]+@/gi,
  /rediss?:\/\/[^\s@]+@/gi,
  /\b(password|password_hash|refresh_token|access_token|authorization|storage_secret_key)\b\s*[:=]\s*[^\s,}]+/gi,
];

function sanitizeString(value: string): string {
  return REDACTIONS.reduce((current, pattern) => current.replace(pattern, '[REDACTED]'), value);
}

function sanitize(value: unknown, seen = new WeakSet<object>()): unknown {
  if (typeof value === 'string') return sanitizeString(value);
  if (typeof value === 'bigint') return value.toString();
  if (value === null || typeof value !== 'object') return value;
  if (value instanceof Error) {
    return { name: value.name, message: sanitizeString(value.message) };
  }
  if (seen.has(value)) return '[Circular]';
  seen.add(value);

  if (Array.isArray(value)) return value.map((item) => sanitize(item, seen));

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      REDACTED_KEYS.has(key.toLowerCase()) ? '[REDACTED]' : sanitize(item, seen),
    ]),
  );
}

@Injectable()
export class JsonLoggerService implements LoggerService {
  log(message: unknown, ...optionalParams: unknown[]): void {
    this.write('info', message, optionalParams);
  }

  error(message: unknown, ...optionalParams: unknown[]): void {
    this.write('error', message, optionalParams);
  }

  warn(message: unknown, ...optionalParams: unknown[]): void {
    this.write('warn', message, optionalParams);
  }

  debug(message: unknown, ...optionalParams: unknown[]): void {
    this.write('debug', message, optionalParams);
  }

  verbose(message: unknown, ...optionalParams: unknown[]): void {
    this.write('trace', message, optionalParams);
  }

  private write(level: string, message: unknown, optionalParams: unknown[]): void {
    const entry = JSON.stringify({
      timestamp: new Date().toISOString(),
      level,
      message: sanitize(message),
      context: optionalParams.map((item) => sanitize(item)),
    });
    if (level === 'error') process.stderr.write(`${entry}\n`);
    else process.stdout.write(`${entry}\n`);
  }
}
