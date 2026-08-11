import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { AppModule } from '../../src/app.module';
import { configureApplication } from '../../src/bootstrap';
import { AppConfigService } from '../../src/config/app-config.service';

export async function createTestApp(): Promise<INestApplication> {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  const app = moduleRef.createNestApplication();
  configureApplication(app, app.get(AppConfigService));
  await app.init();
  return app;
}
