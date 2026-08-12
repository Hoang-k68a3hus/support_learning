import { Module } from '@nestjs/common';
import { Client } from 'minio';
import { AppConfigService } from '../config/app-config.service';
import { MINIO_CLIENT, MinioStorageService } from './minio-storage.service';
import { STORAGE_PORT } from './storage.port';

@Module({
  providers: [
    {
      provide: MINIO_CLIENT,
      inject: [AppConfigService],
      useFactory: (config: AppConfigService): Client => {
        const endpoint = new URL(config.storageEndpoint);
        return new Client({
          endPoint: endpoint.hostname,
          port: endpoint.port ? Number(endpoint.port) : endpoint.protocol === 'https:' ? 443 : 80,
          useSSL: endpoint.protocol === 'https:',
          accessKey: config.storageAccessKey,
          secretKey: config.storageSecretKey,
        });
      },
    },
    MinioStorageService,
    { provide: STORAGE_PORT, useExisting: MinioStorageService },
  ],
  exports: [STORAGE_PORT],
})
export class StorageModule {}
