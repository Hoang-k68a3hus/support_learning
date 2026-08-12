import { Inject, Injectable, ServiceUnavailableException } from '@nestjs/common';
import { Client, CopyConditions } from 'minio';
import { AppConfigService } from '../config/app-config.service';
import { DomainHttpException } from '../common/errors/domain-http.exception';
import type { ExpectedObjectMetadata, StoragePort, StoredObjectMetadata, UploadGrant } from './storage.port';

export const MINIO_CLIENT = Symbol('MINIO_CLIENT');

function errorCode(error: unknown): string | undefined {
  if (typeof error !== 'object' || error === null) return undefined;
  const candidate = error as { code?: unknown };
  return typeof candidate.code === 'string' ? candidate.code : undefined;
}

function contentType(metaData: unknown): string | null {
  if (typeof metaData !== 'object' || metaData === null) return null;
  const values = metaData as Record<string, unknown>;
  const raw = values['content-type'] ?? values['Content-Type'] ?? values['Content-type'];
  if (typeof raw !== 'string' || raw.trim().length === 0) return null;
  const [type] = raw.split(';', 1);
  return type?.trim().toLowerCase() ?? null;
}

@Injectable()
export class MinioStorageService implements StoragePort {
  private bucketReady: Promise<void> | null = null;

  constructor(
    private readonly config: AppConfigService,
    @Inject(MINIO_CLIENT) private readonly client: Client,
  ) {}

  async createUploadGrant(stagingObjectKey: string, expected: ExpectedObjectMetadata): Promise<UploadGrant> {
    await this.ensureBucket();
    const expiresAt = new Date(Date.now() + this.config.storageUploadTtlSeconds * 1000);
    try {
      const url = await this.client.presignedPutObject(
        this.config.storageBucket,
        stagingObjectKey,
        this.config.storageUploadTtlSeconds,
      );
      return { url, expiresAt, requiredHeaders: { 'Content-Type': expected.mediaType } };
    } catch (error) {
      throw this.storageUnavailable('Unable to create upload URL');
    }
  }

  async statObject(objectKey: string): Promise<StoredObjectMetadata | null> {
    await this.ensureBucket();
    try {
      const stat = await this.client.statObject(this.config.storageBucket, objectKey);
      return {
        sizeBytes: stat.size,
        etag: stat.etag,
        mediaType: contentType(stat.metaData),
        checksumSha256: null,
      };
    } catch (error) {
      const code = errorCode(error);
      if (code === 'NoSuchKey' || code === 'NotFound' || code === 'NoSuchObject') return null;
      throw this.storageUnavailable('Unable to inspect stored object');
    }
  }

  async finalizeObject(
    stagingObjectKey: string,
    finalObjectKey: string,
    expected: ExpectedObjectMetadata,
  ): Promise<StoredObjectMetadata> {
    const staging = await this.statObject(stagingObjectKey);
    if (!staging) {
      throw new DomainHttpException(409, 'UPLOAD_SOURCE_MISSING', 'Uploaded staging object does not exist');
    }
    this.assertExpected(staging, expected, 'Staging object metadata does not match the upload contract');

    const existingFinal = await this.statObject(finalObjectKey);
    if (existingFinal) {
      this.assertExpected(existingFinal, expected, 'Final object conflicts with the committed upload contract');
      return existingFinal;
    }

    const conditions = new CopyConditions();
    conditions.setMatchETag(staging.etag);
    try {
      await this.client.copyObject(
        this.config.storageBucket,
        finalObjectKey,
        `/${this.config.storageBucket}/${stagingObjectKey}`,
        conditions,
      );
    } catch (error) {
      const code = errorCode(error);
      if (code === 'PreconditionFailed') {
        throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', 'Staging object changed while it was being finalized');
      }
      throw this.storageUnavailable('Unable to finalize uploaded object');
    }

    const finalObject = await this.statObject(finalObjectKey);
    if (!finalObject) throw new ServiceUnavailableException('Final object verification failed');
    this.assertExpected(finalObject, expected, 'Final object metadata does not match the upload contract');
    return finalObject;
  }

  private assertExpected(actual: StoredObjectMetadata, expected: ExpectedObjectMetadata, detail: string): void {
    if (actual.sizeBytes !== expected.sizeBytes || actual.mediaType !== expected.mediaType.toLowerCase()) {
      throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', detail);
    }
  }

  private async ensureBucket(): Promise<void> {
    this.bucketReady ??= this.ensureBucketOnce().catch((error: unknown) => {
      this.bucketReady = null;
      throw error;
    });
    await this.bucketReady;
  }

  private async ensureBucketOnce(): Promise<void> {
    try {
      const exists = await this.client.bucketExists(this.config.storageBucket);
      if (exists) return;
      if (this.config.isProduction) throw new ServiceUnavailableException('Configured storage bucket does not exist');
      await this.client.makeBucket(this.config.storageBucket);
    } catch (error) {
      if (error instanceof ServiceUnavailableException) throw error;
      const code = errorCode(error);
      if (code === 'BucketAlreadyOwnedByYou' || code === 'BucketAlreadyExists') return;
      throw this.storageUnavailable('Object storage is unavailable');
    }
  }

  private storageUnavailable(detail: string): ServiceUnavailableException {
    return new ServiceUnavailableException(detail);
  }
}
