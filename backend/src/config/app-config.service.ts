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

  get isProduction(): boolean {
    return this.nodeEnv === 'production';
  }
}
