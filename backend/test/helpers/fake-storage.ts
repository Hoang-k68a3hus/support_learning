import { createHash } from 'node:crypto';
import { DomainHttpException } from '../../src/common/errors/domain-http.exception';
import type { ExpectedObjectMetadata, StoragePort, StoredObjectMetadata, UploadGrant } from '../../src/storage/storage.port';

interface FakeObject {
  body: Buffer;
  mediaType: string;
  etag: string;
  checksumSha256: string;
}

export class FakeStorage implements StoragePort {
  private readonly objects = new Map<string, FakeObject>();

  putObject(key: string, body: Buffer | string, mediaType: string): StoredObjectMetadata {
    const bytes = Buffer.isBuffer(body) ? Buffer.from(body) : Buffer.from(body, 'utf8');
    const digest = createHash('sha256').update(bytes).digest('hex');
    const object: FakeObject = {
      body: bytes,
      mediaType: mediaType.toLowerCase(),
      etag: digest.slice(0, 32),
      checksumSha256: digest,
    };
    this.objects.set(key, object);
    return this.metadata(object);
  }

  readObject(key: string): Buffer | null {
    const object = this.objects.get(key);
    return object ? Buffer.from(object.body) : null;
  }

  createUploadGrant(stagingObjectKey: string, expected: ExpectedObjectMetadata): Promise<UploadGrant> {
    return Promise.resolve({
      url: `https://storage.test/${encodeURIComponent(stagingObjectKey)}`,
      expiresAt: new Date(Date.now() + 15 * 60 * 1000),
      requiredHeaders: { 'Content-Type': expected.mediaType },
    });
  }

  statObject(objectKey: string): Promise<StoredObjectMetadata | null> {
    const object = this.objects.get(objectKey);
    return Promise.resolve(object ? this.metadata(object) : null);
  }

  finalizeObject(
    stagingObjectKey: string,
    finalObjectKey: string,
    expected: ExpectedObjectMetadata,
  ): Promise<StoredObjectMetadata> {
    const staging = this.objects.get(stagingObjectKey);
    if (!staging) return Promise.reject(new DomainHttpException(409, 'UPLOAD_SOURCE_MISSING', 'Uploaded staging object does not exist'));

    try {
      this.assertExpected(staging, expected);
      const existing = this.objects.get(finalObjectKey);
      if (existing) {
        this.assertExpected(existing, expected);
        return Promise.resolve(this.metadata(existing));
      }

      const finalized: FakeObject = {
        body: Buffer.from(staging.body),
        mediaType: staging.mediaType,
        etag: staging.etag,
        checksumSha256: staging.checksumSha256,
      };
      this.objects.set(finalObjectKey, finalized);
      return Promise.resolve(this.metadata(finalized));
    } catch (error) {
      return Promise.reject(error instanceof Error ? error : new Error('Fake storage finalization failed'));
    }
  }

  private assertExpected(object: FakeObject, expected: ExpectedObjectMetadata): void {
    if (object.body.length !== expected.sizeBytes || object.mediaType !== expected.mediaType.toLowerCase()) {
      throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', 'Object metadata does not match the upload contract');
    }
  }

  private metadata(object: FakeObject): StoredObjectMetadata {
    return {
      sizeBytes: object.body.length,
      etag: object.etag,
      mediaType: object.mediaType,
      checksumSha256: object.checksumSha256,
    };
  }
}
