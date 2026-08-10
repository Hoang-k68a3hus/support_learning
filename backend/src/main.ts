import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { configureApplication } from './bootstrap';
import { JsonLoggerService } from './common/logging/json-logger.service';
import { AppConfigService } from './config/app-config.service';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { bufferLogs: true });
  const config = app.get(AppConfigService);
  app.useLogger(app.get(JsonLoggerService));
  configureApplication(app, config);
  await app.listen(config.port, '0.0.0.0');
}

void bootstrap();
