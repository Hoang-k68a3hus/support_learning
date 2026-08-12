import type { INestApplication } from '@nestjs/common';
import { DocumentUploadState } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import { PrismaService } from '../../src/database/prisma.service';
import { createTestApp } from '../helpers/test-app';

describe('M3 source-fact database immutability', () => {
  let app: INestApplication;
  let prisma: PrismaService;

  beforeAll(async () => {
    app = await createTestApp();
    prisma = app.get(PrismaService);
  });

  beforeEach(async () => {
    await prisma.$transaction(async (tx) => {
      await tx.workspaceSource.deleteMany();
      await tx.documentTag.deleteMany();
      await tx.auditLog.deleteMany();
      await tx.outboxEvent.deleteMany();
      await tx.idempotencyRecord.deleteMany();
      await tx.document.updateMany({ data: { currentVersionId: null } });
      await tx.documentSource.deleteMany();
      await tx.documentVersion.deleteMany();
      await tx.document.deleteMany();
      await tx.tag.deleteMany();
      await tx.folder.deleteMany();
      await tx.workspace.deleteMany();
      await tx.session.deleteMany();
      await tx.user.deleteMany();
    });
  });

  afterAll(async () => {
    await app.close();
  });

  it('requires verified source metadata before RECEIVED and rejects later source/version mutation', async () => {
    const suffix = randomUUID();
    const user = await prisma.user.create({
      data: {
        email: `immutable-${suffix}@example.com`,
        normalizedEmail: `immutable-${suffix}@example.com`,
        passwordHash: 'not-used-in-this-test',
      },
    });
    const document = await prisma.document.create({ data: { ownerId: user.id, title: 'Immutable source' } });
    const version = await prisma.documentVersion.create({ data: { documentId: document.id, versionNo: 1 } });
    const source = await prisma.documentSource.create({
      data: {
        documentVersionId: version.id,
        stagingObjectKey: `uploads/${suffix}/source`,
        objectKey: `documents/${document.id}/versions/${version.id}/source`,
        originalFilename: 'source.txt',
        mediaType: 'text/plain',
        sizeBytes: BigInt(5),
      },
    });

    await expect(
      prisma.documentVersion.update({ where: { id: version.id }, data: { uploadState: DocumentUploadState.RECEIVED } }),
    ).rejects.toThrow();

    const verifiedAt = new Date();
    await prisma.documentSource.update({
      where: { id: source.id },
      data: { etag: 'verified-etag', checksumSha256: 'a'.repeat(64), verifiedAt },
    });
    await prisma.documentVersion.update({ where: { id: version.id }, data: { uploadState: DocumentUploadState.RECEIVED } });

    await expect(prisma.documentVersion.update({ where: { id: version.id }, data: { versionNo: 2 } })).rejects.toThrow();
    await expect(prisma.documentVersion.update({ where: { id: version.id }, data: { uploadState: DocumentUploadState.UPLOADING } })).rejects.toThrow();
    await expect(prisma.documentSource.update({ where: { id: source.id }, data: { originalFilename: 'rewritten.txt' } })).rejects.toThrow();
    await expect(prisma.documentSource.update({ where: { id: source.id }, data: { objectKey: `documents/${document.id}/rewritten` } })).rejects.toThrow();

    const persistedVersion = await prisma.documentVersion.findUniqueOrThrow({ where: { id: version.id } });
    const persistedSource = await prisma.documentSource.findUniqueOrThrow({ where: { id: source.id } });
    expect(persistedVersion.versionNo).toBe(1);
    expect(persistedVersion.uploadState).toBe(DocumentUploadState.RECEIVED);
    expect(persistedSource.originalFilename).toBe('source.txt');
    expect(persistedSource.objectKey).toBe(`documents/${document.id}/versions/${version.id}/source`);
    expect(persistedSource.verifiedAt?.getTime()).toBe(verifiedAt.getTime());
  });
});
