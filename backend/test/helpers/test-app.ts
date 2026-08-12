import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { AppModule } from '../../src/app.module';
import { configureApplication } from '../../src/bootstrap';
import { AppConfigService } from '../../src/config/app-config.service';
import { STORAGE_PORT, type StoragePort } from '../../src/storage/storage.port';

export async function createTestApp(options?: { storagePort?: StoragePort }): Promise<INestApplication> {
  const builder = Test.createTestingModule({ imports: [AppModule] });
  if (options?.storagePort) builder.overrideProvider(STORAGE_PORT).useValue(options.storagePort);
  const moduleRef = await builder.compile();
  const app = moduleRef.createNestApplication();
  configureApplication(app, app.get(AppConfigService));
  await app.init();
  return app;
}
