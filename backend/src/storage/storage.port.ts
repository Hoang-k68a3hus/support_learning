export const STORAGE_PORT = Symbol('STORAGE_PORT');

export interface UploadGrant {
  url: string;
  expiresAt: Date;
  requiredHeaders: Record<string, string>;
}

export interface StoredObjectMetadata {
  sizeBytes: number;
  etag: string;
  mediaType: string | null;
  checksumSha256: string | null;
}

export interface ExpectedObjectMetadata {
  sizeBytes: number;
  mediaType: string;
}

export interface StoragePort {
  createUploadGrant(stagingObjectKey: string, expected: ExpectedObjectMetadata): Promise<UploadGrant>;
  statObject(objectKey: string): Promise<StoredObjectMetadata | null>;
  finalizeObject(stagingObjectKey: string, finalObjectKey: string, expected: ExpectedObjectMetadata): Promise<StoredObjectMetadata>;
}
