import { MiddlewareConsumer, Module, type NestModule } from '@nestjs/common';
import { APP_FILTER, APP_INTERCEPTOR } from '@nestjs/core';
import { AuthModule } from './auth/auth.module';
import { HttpExceptionFilter } from './common/errors/http-exception.filter';
import { JsonLoggerService } from './common/logging/json-logger.service';
import { RequestLoggingInterceptor } from './common/logging/request-logging.interceptor';
import { RequestIdMiddleware } from './common/middleware/request-id.middleware';
import { ConfigModule } from './config/config.module';
import { PrismaModule } from './database/prisma.module';
import { HealthModule } from './health/health.module';
import { UsersModule } from './users/users.module';

@Module({
  imports: [ConfigModule, PrismaModule, HealthModule, AuthModule, UsersModule],
  providers: [
    JsonLoggerService,
    { provide: APP_FILTER, useClass: HttpExceptionFilter },
    { provide: APP_INTERCEPTOR, useClass: RequestLoggingInterceptor },
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    consumer.apply(RequestIdMiddleware).forRoutes('{*splat}');
  }
}
