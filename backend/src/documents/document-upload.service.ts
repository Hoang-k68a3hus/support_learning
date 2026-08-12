import { ConflictException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { DocumentStatus, DocumentUploadState, Prisma, type DocumentSource, type DocumentVersion } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import { DomainHttpException } from '../common/errors/domain-http.exception';
import { AppConfigService } from '../config/app-config.service';
import { PrismaService } from '../database/prisma.service';
import { IdempotencyService } from '../idempotency/idempotency.service';
import { OutboxService } from '../outbox/outbox.service';
import { STORAGE_PORT, type StoragePort, type StoredObjectMetadata } from '../storage/storage.port';
import type { InitUploadDto, NewVersionInitUploadDto } from './dto/document.dto';

interface UploadLogicalResponse {
  documentId: string;
  versionId: string;
  uploadState: DocumentUploadState;
}

type VersionWithSource = DocumentVersion & { source: DocumentSource | null };

function asLogicalResponse(value: Prisma.JsonValue): UploadLogicalResponse {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Corrupt idempotency response');
  const object = value as Prisma.JsonObject;
  const documentId = object.documentId;
  const versionId = object.versionId;
  const uploadState = object.uploadState;
  if (typeof documentId !== 'string' || typeof versionId !== 'string' || uploadState !== DocumentUploadState.UPLOADING) {
    throw new Error('Corrupt idempotency response');
  }
  return { documentId, versionId, uploadState };
}

@Injectable()
export class DocumentUploadService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly config: AppConfigService,
    private readonly idempotency: IdempotencyService,
    private readonly outbox: OutboxService,
    @Inject(STORAGE_PORT) private readonly storage: StoragePort,
  ) {}

  async initDocument(ownerId: string, rawKey: string | undefined, dto: InitUploadDto) {
    this.assertUploadPolicy(dto.sizeBytes, dto.mediaType);
    const key = this.idempotency.validateKey(rawKey);
    const scope = 'documents:init-upload';
    const requestHash = this.idempotency.canonicalHashV1({
      title: dto.title,
      folderId: dto.folderId ?? null,
      originalFilename: dto.originalFilename,
      mediaType: dto.mediaType,
      sizeBytes: dto.sizeBytes,
    });

    const documentId = randomUUID();
    const versionId = randomUUID();
    const uploadId = randomUUID();
    const stagingObjectKey = `uploads/${uploadId}/source`;
    const objectKey = `documents/${documentId}/versions/${versionId}/source`;

    const logical = await this.prisma.$transaction(async (tx) => {
      const existing = await this.idempotency.lockAndFind(tx, ownerId, scope, key, requestHash);
      if (existing) return asLogicalResponse(existing.responseBody);
      if (dto.folderId) await this.assertOwnedFolder(tx, ownerId, dto.folderId);

      await tx.document.create({
        data: { id: documentId, ownerId, folderId: dto.folderId ?? null, title: dto.title, status: DocumentStatus.ACTIVE },
      });
      await tx.documentVersion.create({
        data: { id: versionId, documentId, versionNo: 1, uploadState: DocumentUploadState.UPLOADING },
      });
      await tx.documentSource.create({
        data: {
          documentVersionId: versionId,
          stagingObjectKey,
          objectKey,
          originalFilename: dto.originalFilename,
          mediaType: dto.mediaType,
          sizeBytes: BigInt(dto.sizeBytes),
        },
      });
      const response: UploadLogicalResponse = { documentId, versionId, uploadState: DocumentUploadState.UPLOADING };
      await this.idempotency.createRecord(tx, {
        userId: ownerId,
        scope,
        key,
        requestHash,
        responseStatus: 201,
        responseBody: response as unknown as Prisma.InputJsonValue,
      });
      return response;
    });

    return this.withUploadGrant(logical);
  }

  async initNewVersion(ownerId: string, documentId: string, rawKey: string | undefined, dto: NewVersionInitUploadDto) {
    this.assertUploadPolicy(dto.sizeBytes, dto.mediaType);
    const key = this.idempotency.validateKey(rawKey);
    const scope = `documents:${documentId}:versions:init-upload`;
    const requestHash = this.idempotency.canonicalHashV1({
      originalFilename: dto.originalFilename,
      mediaType: dto.mediaType,
      sizeBytes: dto.sizeBytes,
    });

    const versionId = randomUUID();
    const uploadId = randomUUID();
    const stagingObjectKey = `uploads/${uploadId}/source`;
    const objectKey = `documents/${documentId}/versions/${versionId}/source`;

    const logical = await this.prisma.$transaction(async (tx) => {
      const existing = await this.idempotency.lockAndFind(tx, ownerId, scope, key, requestHash);
      if (existing) return asLogicalResponse(existing.responseBody);

      const locked = await tx.$queryRaw<Array<{ id: string }>>`
        SELECT "id" FROM "documents"
        WHERE "id" = ${documentId}::uuid AND "owner_id" = ${ownerId}::uuid
          AND "status" = 'ACTIVE' AND "deleted_at" IS NULL
        FOR UPDATE
      `;
      if (locked.length !== 1) throw new NotFoundException('Document not found');
      const latest = await tx.documentVersion.findFirst({ where: { documentId }, orderBy: { versionNo: 'desc' }, select: { versionNo: true } });
      const versionNo = (latest?.versionNo ?? 0) + 1;
      await tx.documentVersion.create({
        data: { id: versionId, documentId, versionNo, uploadState: DocumentUploadState.UPLOADING },
      });
      await tx.documentSource.create({
        data: {
          documentVersionId: versionId,
          stagingObjectKey,
          objectKey,
          originalFilename: dto.originalFilename,
          mediaType: dto.mediaType,
          sizeBytes: BigInt(dto.sizeBytes),
        },
      });
      const response: UploadLogicalResponse = { documentId, versionId, uploadState: DocumentUploadState.UPLOADING };
      await this.idempotency.createRecord(tx, {
        userId: ownerId,
        scope,
        key,
        requestHash,
        responseStatus: 201,
        responseBody: response as unknown as Prisma.InputJsonValue,
      });
      return response;
    });

    return this.withUploadGrant(logical);
  }

  async complete(ownerId: string, documentId: string, versionId: string) {
    const before = await this.getOwnedVersion(ownerId, documentId, versionId);
    if (!before.source) throw new Error('DocumentVersion is missing DocumentSource');
    if (before.uploadState === DocumentUploadState.ABORTED) throw new ConflictException('Aborted upload cannot be completed');

    if (before.uploadState === DocumentUploadState.RECEIVED) {
      await this.assertReceivedObject(before.source);
      const document = await this.prisma.document.findFirst({
        where: { id: documentId, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null },
        select: { currentVersionId: true },
      });
      if (!document) throw new NotFoundException('Document not found');
      return { documentId, versionId, uploadState: DocumentUploadState.RECEIVED, currentVersionId: document.currentVersionId, statusUrl: `/api/v1/documents/${documentId}/status` };
    }

    const finalized = await this.storage.finalizeObject(before.source.stagingObjectKey, before.source.objectKey, {
      sizeBytes: Number(before.source.sizeBytes),
      mediaType: before.source.mediaType,
    });

    return this.prisma.$transaction(async (tx) => {
      const locked = await tx.$queryRaw<Array<{ currentVersionId: string | null; currentVersionNo: number | null }>>`
        SELECT d."current_version_id" AS "currentVersionId", cv."version_no" AS "currentVersionNo"
        FROM "documents" d
        LEFT JOIN "document_versions" cv ON cv."id" = d."current_version_id"
        WHERE d."id" = ${documentId}::uuid AND d."owner_id" = ${ownerId}::uuid
          AND d."status" = 'ACTIVE' AND d."deleted_at" IS NULL
        FOR UPDATE OF d
      `;
      const document = locked[0];
      if (!document) throw new NotFoundException('Document not found');

      const target = await tx.documentVersion.findFirst({
        where: { id: versionId, documentId },
        include: { source: true },
      });
      if (!target?.source) throw new NotFoundException('Document version not found');
      if (target.uploadState === DocumentUploadState.ABORTED) throw new ConflictException('Aborted upload cannot be completed');
      if (target.uploadState === DocumentUploadState.RECEIVED) {
        this.assertStoredMetadataMatchesSource(finalized, target.source);
        return {
          documentId,
          versionId,
          uploadState: DocumentUploadState.RECEIVED,
          currentVersionId: document.currentVersionId,
          statusUrl: `/api/v1/documents/${documentId}/status`,
        };
      }

      this.assertExpectedMetadata(finalized, target.source);
      const now = new Date();
      await tx.documentSource.update({
        where: { documentVersionId: versionId },
        data: {
          sizeBytes: BigInt(finalized.sizeBytes),
          mediaType: finalized.mediaType ?? target.source.mediaType,
          etag: finalized.etag,
          checksumSha256: finalized.checksumSha256,
          verifiedAt: now,
        },
      });
      await tx.documentVersion.update({
        where: { id: versionId },
        data: { uploadState: DocumentUploadState.RECEIVED },
      });

      const promote = document.currentVersionNo === null || target.versionNo > document.currentVersionNo;
      const currentVersionId = promote ? versionId : document.currentVersionId;
      if (promote) await tx.document.update({ where: { id: documentId }, data: { currentVersionId: versionId } });

      await this.outbox.append(tx, {
        aggregateType: 'DocumentVersion',
        aggregateId: versionId,
        eventType: 'DOCUMENT_VERSION_RECEIVED',
        payload: { ownerId, documentId, documentVersionId: versionId, versionNo: target.versionNo },
      });

      return {
        documentId,
        versionId,
        uploadState: DocumentUploadState.RECEIVED,
        currentVersionId,
        statusUrl: `/api/v1/documents/${documentId}/status`,
      };
    });
  }

  private async withUploadGrant(logical: UploadLogicalResponse) {
    const source = await this.prisma.documentSource.findUnique({ where: { documentVersionId: logical.versionId } });
    if (!source) throw new Error('Upload source was not persisted');
    const grant = await this.storage.createUploadGrant(source.stagingObjectKey, {
      sizeBytes: Number(source.sizeBytes),
      mediaType: source.mediaType,
    });
    return {
      ...logical,
      uploadUrl: grant.url,
      expiresAt: grant.expiresAt,
      requiredHeaders: grant.requiredHeaders,
    };
  }

  private assertUploadPolicy(sizeBytes: number, mediaType: string): void {
    if (sizeBytes > this.config.storageMaxUploadBytes) {
      throw new DomainHttpException(413, 'UPLOAD_TOO_LARGE', `Upload exceeds the ${this.config.storageMaxUploadBytes} byte limit`);
    }
    if (!this.config.storageAllowedMediaTypes.includes(mediaType.toLowerCase())) {
      throw new DomainHttpException(422, 'UNSUPPORTED_MEDIA_TYPE', 'Media type is not allowed for document uploads');
    }
  }

  private async assertOwnedFolder(tx: Prisma.TransactionClient, ownerId: string, folderId: string): Promise<void> {
    const folder = await tx.folder.findFirst({ where: { id: folderId, ownerId, deletedAt: null }, select: { id: true } });
    if (!folder) throw new NotFoundException('Folder not found');
  }

  private async getOwnedVersion(ownerId: string, documentId: string, versionId: string): Promise<VersionWithSource> {
    const version = await this.prisma.documentVersion.findFirst({
      where: {
        id: versionId,
        documentId,
        document: { ownerId, status: DocumentStatus.ACTIVE, deletedAt: null },
      },
      include: { source: true },
    });
    if (!version) throw new NotFoundException('Document version not found');
    return version;
  }

  private async assertReceivedObject(source: DocumentSource): Promise<void> {
    const actual = await this.storage.statObject(source.objectKey);
    if (!actual) throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', 'Final object for RECEIVED version is missing');
    this.assertStoredMetadataMatchesSource(actual, source);
  }

  private assertExpectedMetadata(actual: StoredObjectMetadata, source: DocumentSource): void {
    if (actual.sizeBytes !== Number(source.sizeBytes) || actual.mediaType !== source.mediaType.toLowerCase()) {
      throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', 'Final object metadata does not match the upload contract');
    }
  }

  private assertStoredMetadataMatchesSource(actual: StoredObjectMetadata, source: DocumentSource): void {
    this.assertExpectedMetadata(actual, source);
    if (!source.verifiedAt || !source.etag || actual.etag !== source.etag || actual.checksumSha256 !== source.checksumSha256) {
      throw new DomainHttpException(409, 'DATA_INTEGRITY_CONFLICT', 'Final object metadata conflicts with the persisted RECEIVED source');
    }
  }
}
