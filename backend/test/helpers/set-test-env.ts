process.env.NODE_ENV = 'test';
process.env.PORT = process.env.PORT ?? '3001';
process.env.JWT_ACCESS_SECRET = process.env.JWT_ACCESS_SECRET ?? 'test-access-secret-only-32-characters-minimum';
process.env.JWT_ACCESS_TTL = process.env.JWT_ACCESS_TTL ?? '15m';
process.env.JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET ?? 'test-refresh-secret-only-32-characters-minimum-different';
process.env.JWT_REFRESH_TTL = process.env.JWT_REFRESH_TTL ?? '7d';
process.env.CORS_ORIGIN = process.env.CORS_ORIGIN ?? 'http://localhost:3000';

if (!process.env.DATABASE_URL) {
  throw new Error('DATABASE_URL is required for integration/E2E tests');
}
