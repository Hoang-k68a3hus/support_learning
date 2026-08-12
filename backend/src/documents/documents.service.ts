import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { DocumentStatus, type Document, type DocumentSource, type DocumentUploadState, type DocumentVersion } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import type { CursorPage } from '../common/types/pagination';
import { PrismaService } from '../database/prisma.service';
import type { ListDocumentsQueryDto, ListVersionsQueryDto, UpdateDocumentDto } from './dto/document.dto';

export interface VersionDto {
  id: string;
  versionNo: number;
  uploadState: string;
  source: {
    originalFilename: string;
    mediaType: string;
    sizeBytes: number;
    etag: string | null;
    checksumSha256: string | null;
    verifiedAt: Date | null;
  } | null;
  createdAt: Date;
}

export interface DocumentDto {
  id: string;
  title: string;
  folderId: string | null;
  status: string;
  currentVersion: VersionDto | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface DocumentStatusDto {
  documentId: string;
  status: DocumentStatus;
  currentVersionId: string | null;
  latestVersion: { id: string; versionNo: number; uploadState: DocumentUploadState } | null;
}

type VersionWithSource = DocumentVersion & { source: DocumentSource | null };

function versionDto(version: VersionWithSource): VersionDto {
  return {
    id: version.id,
    versionNo: version.versionNo,
    uploadState: version.uploadState,
    source: version.source
      ? {
          originalFilename: version.source.originalFilename,
          mediaType: version.source.mediaType,
          sizeBytes: Number(version.source.sizeBytes),
          etag: version.source.etag,
          checksumSha256: version.source.checksumSha256,
          verifiedAt: version.source.verifiedAt,
        }
      : null,
    createdAt: version.createdAt,
  };
}

@Injectable()
export class DocumentsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  async list(ownerId: string, query: ListDocumentsQueryDto): Promise<CursorPage<DocumentDto>> {
    if (query.folderId) await this.assertOwnedFolder(ownerId, query.folderId);
    if (query.tagId) {
      const tag = await this.prisma.tag.findFirst({ where: { id: query.tagId, ownerId }, select: { id: true } });
      if (!tag) throw new NotFoundException('Tag not found');
    }
    if (query.cursor) {
      const cursor = await this.prisma.document.findFirst({
        where: { id: query.cursor, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null },
        select: { id: true },
      });
      if (!cursor) throw new BadRequestException('Invalid document cursor');
    }

    let taggedDocumentIds: string[] | undefined;
    if (query.tagId) {
      const links = await this.prisma.documentTag.findMany({
        where: { ownerId, tagId: query.tagId },
        select: { documentId: true },
      });
      taggedDocumentIds = links.map((row) => row.documentId);
      if (taggedDocumentIds.length === 0) return { items: [], nextCursor: null };
    }

    const rows = await this.prisma.document.findMany({
      where: {
        ownerId,
        status: DocumentStatus.ACTIVE,
        deletedAt: null,
        ...(query.folderId ? { folderId: query.folderId } : {}),
        ...(taggedDocumentIds ? { id: { in: taggedDocumentIds } } : {}),
      },
      orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
      take: query.limit + 1,
      ...(query.cursor ? { cursor: { id: query.cursor }, skip: 1 } : {}),
    });
    const hasMore = rows.length > query.limit;
    const page = hasMore ? rows.slice(0, query.limit) : rows;
    const dto = await this.attachCurrentVersions(page);
    return { items: dto, nextCursor: hasMore ? page.at(-1)?.id ?? null : null };
  }

  async get(ownerId: string, id: string): Promise<DocumentDto> {
    const document = await this.getOwnedActive(ownerId, id);
    return (await this.attachCurrentVersions([document]))[0]!;
  }

  async update(ownerId: string, id: string, dto: UpdateDocumentDto, requestId: string): Promise<DocumentDto> {
    if (dto.title === undefined && dto.folderId === undefined) throw new BadRequestException('At least one mutable field is required');
    const document = await this.getOwnedActive(ownerId, id);
    if (dto.folderId) await this.assertOwnedFolder(ownerId, dto.folderId);

    const updated = await this.prisma.$transaction(async (tx) => {
      const row = await tx.document.update({
        where: { id },
        data: {
          ...(dto.title !== undefined ? { title: dto.title } : {}),
          ...(dto.folderId !== undefined ? { folderId: dto.folderId } : {}),
        },
      });
      if (dto.folderId !== undefined && document.folderId !== dto.folderId) {
        await this.audit.append(tx, {
          actorUserId: ownerId,
          action: 'DOCUMENT_MOVED',
          resourceType: 'Document',
          resourceId: id,
          requestId,
          metadata: { fromFolderId: document.folderId, toFolderId: dto.folderId },
        });
      }
      return row;
    });
    return (await this.attachCurrentVersions([updated]))[0]!;
  }

  async delete(ownerId: string, id: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const document = await tx.document.findFirst({ where: { id, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null } });
      if (!document) throw new NotFoundException('Document not found');
      const deletedAt = new Date();
      await tx.workspaceSource.deleteMany({ where: { documentId: id, ownerId } });
      await tx.documentTag.deleteMany({ where: { documentId: id, ownerId } });
      await tx.document.update({ where: { id }, data: { status: DocumentStatus.DELETED, deletedAt } });
      await this.audit.append(tx, {
        actorUserId: ownerId,
        action: 'DOCUMENT_DELETED',
        resourceType: 'Document',
        resourceId: id,
        requestId,
      });
    });
  }

  async listVersions(ownerId: string, documentId: string, query: ListVersionsQueryDto): Promise<CursorPage<VersionDto>> {
    await this.getOwnedActive(ownerId, documentId);
    if (query.cursor) {
      const cursor = await this.prisma.documentVersion.findFirst({ where: { id: query.cursor, documentId }, select: { id: true } });
      if (!cursor) throw new BadRequestException('Invalid version cursor');
    }
    const rows = await this.prisma.documentVersion.findMany({
      where: { documentId },
      include: { source: true },
      orderBy: [{ versionNo: 'desc' }, { id: 'desc' }],
      take: query.limit + 1,
      ...(query.cursor ? { cursor: { id: query.cursor }, skip: 1 } : {}),
    });
    const hasMore = rows.length > query.limit;
    const page = hasMore ? rows.slice(0, query.limit) : rows;
    return { items: page.map(versionDto), nextCursor: hasMore ? page.at(-1)?.id ?? null : null };
  }

  async getStatus(ownerId: string, documentId: string): Promise<DocumentStatusDto> {
    const document = await this.getOwnedActive(ownerId, documentId);
    const latest = await this.prisma.documentVersion.findFirst({
      where: { documentId },
      orderBy: { versionNo: 'desc' },
      select: { id: true, versionNo: true, uploadState: true },
    });
    return {
      documentId,
      status: document.status,
      currentVersionId: document.currentVersionId,
      latestVersion: latest,
    };
  }

  async linkTag(ownerId: string, documentId: string, tagId: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const [document, tag] = await Promise.all([
        tx.document.findFirst({ where: { id: documentId, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null }, select: { id: true } }),
        tx.tag.findFirst({ where: { id: tagId, ownerId }, select: { id: true } }),
      ]);
      if (!document || !tag) throw new NotFoundException('Document or tag not found');
      const created = await tx.documentTag.createMany({ data: [{ documentId, tagId, ownerId }], skipDuplicates: true });
      if (created.count === 1) {
        await this.audit.append(tx, {
          actorUserId: ownerId,
          action: 'DOCUMENT_TAG_LINKED',
          resourceType: 'Document',
          resourceId: documentId,
          requestId,
          metadata: { tagId },
        });
      }
    });
  }

  async unlinkTag(ownerId: string, documentId: string, tagId: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const document = await tx.document.findFirst({
        where: { id: documentId, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null },
        select: { id: true },
      });
      if (!document) throw new NotFoundException('Document not found');
      const deleted = await tx.documentTag.deleteMany({ where: { documentId, tagId, ownerId } });
      if (deleted.count === 1) {
        await this.audit.append(tx, {
          actorUserId: ownerId,
          action: 'DOCUMENT_TAG_UNLINKED',
          resourceType: 'Document',
          resourceId: documentId,
          requestId,
          metadata: { tagId },
        });
      }
    });
  }

  private async getOwnedActive(ownerId: string, id: string): Promise<Document> {
    const document = await this.prisma.document.findFirst({ where: { id, ownerId, status: DocumentStatus.ACTIVE, deletedAt: null } });
    if (!document) throw new NotFoundException('Document not found');
    return document;
  }

  private async assertOwnedFolder(ownerId: string, folderId: string): Promise<void> {
    const folder = await this.prisma.folder.findFirst({ where: { id: folderId, ownerId, deletedAt: null }, select: { id: true } });
    if (!folder) throw new NotFoundException('Folder not found');
  }

  private async attachCurrentVersions(documents: Document[]): Promise<DocumentDto[]> {
    const versionIds = documents.flatMap((document) => (document.currentVersionId ? [document.currentVersionId] : []));
    const versions = versionIds.length
      ? await this.prisma.documentVersion.findMany({ where: { id: { in: versionIds } }, include: { source: true } })
      : [];
    const byId = new Map(versions.map((version) => [version.id, versionDto(version)]));
    return documents.map((document) => ({
      id: document.id,
      title: document.title,
      folderId: document.folderId,
      status: document.status,
      currentVersion: document.currentVersionId ? byId.get(document.currentVersionId) ?? null : null,
      createdAt: document.createdAt,
      updatedAt: document.updatedAt,
    }));
  }
}
