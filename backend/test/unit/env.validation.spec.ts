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
});

describe('validateEnvironment', () => {
  it('accepts valid configuration and parses TTLs', () => {
    const result = validateEnvironment(validEnv());
    expect(result.PORT).toBe(3001);
    expect(result.JWT_ACCESS_TTL_SECONDS).toBe(900);
    expect(result.JWT_REFRESH_TTL_SECONDS).toBe(604800);
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
});
