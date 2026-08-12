import type { INestApplication } from '@nestjs/common';
import { DocumentStatus, DocumentUploadState } from '@prisma/client';
import { randomUUID } from 'node:crypto';
import request from 'supertest';
import { PrismaService } from '../../src/database/prisma.service';
import { FakeStorage } from '../helpers/fake-storage';
import { createTestApp } from '../helpers/test-app';

type SupertestResponse = request.Response;

interface Identity {
  userId: string;
  token: string;
}

interface InitUploadBody {
  title: string;
  folderId?: string;
  originalFilename: string;
  mediaType: string;
  sizeBytes: number;
}

const password = 'correct horse battery staple';
const textUpload = (title = 'Lecture notes'): InitUploadBody => ({
  title,
  originalFilename: 'notes.txt',
  mediaType: 'text/plain',
  sizeBytes: 5,
});

function bearer(token: string): { Authorization: string } {
  return { Authorization: `Bearer ${token}` };
}

describe('M3 Knowledge Library E2E', () => {
  let app: INestApplication;
  let prisma: PrismaService;
  let storage: FakeStorage;

  beforeAll(async () => {
    storage = new FakeStorage();
    app = await createTestApp({ storagePort: storage });
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

  async function identity(label: string): Promise<Identity> {
    const email = `${label}-${randomUUID()}@example.com`;
    const registered = await request(app.getHttpServer()).post('/api/v1/auth/register').send({ email, password }).expect(201);
    const loggedIn = await request(app.getHttpServer()).post('/api/v1/auth/login').send({ email, password }).expect(200);
    return { userId: registered.body.user.id as string, token: loggedIn.body.accessToken as string };
  }

  async function initUpload(user: Identity, key: string, body: InitUploadBody = textUpload()): Promise<SupertestResponse> {
    return request(app.getHttpServer())
      .post('/api/v1/documents/init-upload')
      .set(bearer(user.token))
      .set('Idempotency-Key', key)
      .send(body)
      .expect(201);
  }

  async function uploadVersion(versionId: string, body = 'hello', mediaType = 'text/plain'): Promise<void> {
    const source = await prisma.documentSource.findUniqueOrThrow({ where: { documentVersionId: versionId } });
    storage.putObject(source.stagingObjectKey, body, mediaType);
  }

  async function complete(user: Identity, documentId: string, versionId: string): Promise<SupertestResponse> {
    return request(app.getHttpServer())
      .post(`/api/v1/documents/${documentId}/versions/${versionId}/complete`)
      .set(bearer(user.token))
      .send({})
      .expect(200);
  }

  it('scopes workspaces, folders, tags and documents by authenticated owner and returns 404 across owners', async () => {
    const a = await identity('owner-a');
    const b = await identity('owner-b');

    const workspace = await request(app.getHttpServer()).post('/api/v1/workspaces').set(bearer(a.token)).send({ name: 'Study' }).expect(201);
    const folder = await request(app.getHttpServer()).post('/api/v1/folders').set(bearer(a.token)).send({ name: 'Courses' }).expect(201);
    const tag = await request(app.getHttpServer()).post('/api/v1/tags').set(bearer(a.token)).send({ name: 'Exam' }).expect(201);
    const upload = await initUpload(a, 'owner-a-doc', { ...textUpload(), folderId: folder.body.id as string });

    await request(app.getHttpServer()).get(`/api/v1/workspaces/${workspace.body.id as string}`).set(bearer(b.token)).expect(404);
    await request(app.getHttpServer()).patch(`/api/v1/folders/${folder.body.id as string}`).set(bearer(b.token)).send({ name: 'Other' }).expect(404);
    await request(app.getHttpServer()).patch(`/api/v1/tags/${tag.body.id as string}`).set(bearer(b.token)).send({ name: 'Other' }).expect(404);
    await request(app.getHttpServer()).get(`/api/v1/documents/${upload.body.documentId as string}`).set(bearer(b.token)).expect(404);

    await request(app.getHttpServer())
      .put(`/api/v1/workspaces/${workspace.body.id as string}/sources/${upload.body.documentId as string}`)
      .set(bearer(b.token))
      .expect(404);
    await request(app.getHttpServer())
      .put(`/api/v1/documents/${upload.body.documentId as string}/tags/${tag.body.id as string}`)
      .set(bearer(b.token))
      .expect(404);
  });

  it('enforces folder sibling uniqueness, cycle prevention and non-destructive delete', async () => {
    const user = await identity('folders');
    const root = await request(app.getHttpServer()).post('/api/v1/folders').set(bearer(user.token)).send({ name: 'Root' }).expect(201);
    const child = await request(app.getHttpServer())
      .post('/api/v1/folders')
      .set(bearer(user.token))
      .send({ name: 'Child', parentId: root.body.id })
      .expect(201);

    await request(app.getHttpServer()).post('/api/v1/folders').set(bearer(user.token)).send({ name: ' root ' }).expect(409);
    await request(app.getHttpServer()).patch(`/api/v1/folders/${root.body.id as string}`).set(bearer(user.token)).send({ parentId: root.body.id }).expect(422);
    await request(app.getHttpServer()).patch(`/api/v1/folders/${root.body.id as string}`).set(bearer(user.token)).send({ parentId: child.body.id }).expect(422);
    await request(app.getHttpServer()).delete(`/api/v1/folders/${root.body.id as string}`).set(bearer(user.token)).expect(409);

    expect(await prisma.folder.count({ where: { id: { in: [root.body.id as string, child.body.id as string] }, deletedAt: null } })).toBe(2);
  });

  it('makes init-upload semantically idempotent and writes no processing outbox before completion', async () => {
    const user = await identity('idempotency');
    const first = await initUpload(user, 'same-create', textUpload('Same'));
    const second = await initUpload(user, 'same-create', textUpload('Same'));

    expect(second.body.documentId).toBe(first.body.documentId);
    expect(second.body.versionId).toBe(first.body.versionId);
    expect(first.body.uploadUrl).toContain('storage.test');
    expect(await prisma.document.count({ where: { ownerId: user.userId } })).toBe(1);
    expect(await prisma.documentVersion.count({ where: { documentId: first.body.documentId as string } })).toBe(1);
    expect(await prisma.idempotencyRecord.count({ where: { userId: user.userId } })).toBe(1);
    expect(await prisma.outboxEvent.count()).toBe(0);

    const conflict = await request(app.getHttpServer())
      .post('/api/v1/documents/init-upload')
      .set(bearer(user.token))
      .set('Idempotency-Key', 'same-create')
      .send(textUpload('Different'))
      .expect(409);
    expect(conflict.body.code).toBe('IDEMPOTENCY_CONFLICT');

    await request(app.getHttpServer())
      .post('/api/v1/documents/init-upload')
      .set(bearer(user.token))
      .set('Idempotency-Key', 'forbidden-fields')
      .send({ ...textUpload(), ownerId: user.userId, objectKey: 'attacker/value' })
      .expect(400);
  });

  it('finalizes into immutable final storage, is state-idempotent and emits one outbox event', async () => {
    const user = await identity('complete');
    const upload = await initUpload(user, 'complete-v1');
    const documentId = upload.body.documentId as string;
    const versionId = upload.body.versionId as string;
    const sourceBefore = await prisma.documentSource.findUniqueOrThrow({ where: { documentVersionId: versionId } });

    storage.putObject(sourceBefore.stagingObjectKey, 'hello', 'text/plain');
    const completed = await complete(user, documentId, versionId);
    expect(completed.body).toMatchObject({ documentId, versionId, uploadState: DocumentUploadState.RECEIVED, currentVersionId: versionId });

    const version = await prisma.documentVersion.findUniqueOrThrow({ where: { id: versionId }, include: { source: true } });
    expect(version.uploadState).toBe(DocumentUploadState.RECEIVED);
    expect(version.source?.verifiedAt).toBeTruthy();
    expect(version.source?.etag).toBeTruthy();
    expect(version.source?.checksumSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(storage.readObject(sourceBefore.objectKey)?.toString('utf8')).toBe('hello');
    expect(await prisma.outboxEvent.count({ where: { aggregateId: versionId, eventType: 'DOCUMENT_VERSION_RECEIVED' } })).toBe(1);

    await complete(user, documentId, versionId);
    expect(await prisma.outboxEvent.count({ where: { aggregateId: versionId, eventType: 'DOCUMENT_VERSION_RECEIVED' } })).toBe(1);

    storage.putObject(sourceBefore.stagingObjectKey, 'HELLO', 'text/plain');
    expect(storage.readObject(sourceBefore.objectKey)?.toString('utf8')).toBe('hello');
    await complete(user, documentId, versionId);
  });

  it('serializes concurrent version allocation and keeps currentVersion monotonic under out-of-order completion', async () => {
    const user = await identity('versions');
    const initial = await initUpload(user, 'v1');
    const documentId = initial.body.documentId as string;
    const v1 = initial.body.versionId as string;
    await uploadVersion(v1);
    await complete(user, documentId, v1);

    const endpoint = `/api/v1/documents/${documentId}/versions/init-upload`;
    const [r2, r3] = await Promise.all([
      request(app.getHttpServer()).post(endpoint).set(bearer(user.token)).set('Idempotency-Key', 'new-v-a').send({ originalFilename: 'a.txt', mediaType: 'text/plain', sizeBytes: 5 }),
      request(app.getHttpServer()).post(endpoint).set(bearer(user.token)).set('Idempotency-Key', 'new-v-b').send({ originalFilename: 'b.txt', mediaType: 'text/plain', sizeBytes: 5 }),
    ]);
    expect(r2.status).toBe(201);
    expect(r3.status).toBe(201);
    expect(r2.body.versionId).not.toBe(r3.body.versionId);

    const pending = await prisma.documentVersion.findMany({
      where: { documentId, id: { in: [r2.body.versionId as string, r3.body.versionId as string] } },
      orderBy: { versionNo: 'asc' },
    });
    expect(pending.map((row) => row.versionNo)).toEqual([2, 3]);
    const v2 = pending[0]!;
    const v3 = pending[1]!;
    await uploadVersion(v2.id);
    await uploadVersion(v3.id);

    await complete(user, documentId, v3.id);
    await complete(user, documentId, v2.id);

    const document = await prisma.document.findUniqueOrThrow({ where: { id: documentId } });
    expect(document.currentVersionId).toBe(v3.id);
    const received = await prisma.documentVersion.findMany({ where: { documentId }, orderBy: { versionNo: 'asc' } });
    expect(received.map((row) => row.uploadState)).toEqual([
      DocumentUploadState.RECEIVED,
      DocumentUploadState.RECEIVED,
      DocumentUploadState.RECEIVED,
    ]);
    expect(await prisma.outboxEvent.count({ where: { eventType: 'DOCUMENT_VERSION_RECEIVED' } })).toBe(3);
  });

  it('keeps document source facts when workspace/tag links are removed and records privileged mutations', async () => {
    const user = await identity('links');
    const upload = await initUpload(user, 'linked-doc');
    const documentId = upload.body.documentId as string;
    const workspace = await request(app.getHttpServer()).post('/api/v1/workspaces').set(bearer(user.token)).send({ name: 'Scope' }).expect(201);
    const tag = await request(app.getHttpServer()).post('/api/v1/tags').set(bearer(user.token)).send({ name: 'Important' }).expect(201);

    await request(app.getHttpServer()).put(`/api/v1/workspaces/${workspace.body.id as string}/sources/${documentId}`).set(bearer(user.token)).expect(204);
    await request(app.getHttpServer()).put(`/api/v1/workspaces/${workspace.body.id as string}/sources/${documentId}`).set(bearer(user.token)).expect(204);
    expect(await prisma.workspaceSource.count({ where: { workspaceId: workspace.body.id as string, documentId } })).toBe(1);
    await request(app.getHttpServer()).delete(`/api/v1/workspaces/${workspace.body.id as string}/sources/${documentId}`).set(bearer(user.token)).expect(204);

    await request(app.getHttpServer()).put(`/api/v1/documents/${documentId}/tags/${tag.body.id as string}`).set(bearer(user.token)).expect(204);
    await request(app.getHttpServer()).delete(`/api/v1/tags/${tag.body.id as string}`).set(bearer(user.token)).expect(204);
    await request(app.getHttpServer()).delete(`/api/v1/workspaces/${workspace.body.id as string}`).set(bearer(user.token)).expect(204);

    expect(await prisma.document.count({ where: { id: documentId, status: DocumentStatus.ACTIVE } })).toBe(1);
    expect(await prisma.documentVersion.count({ where: { documentId } })).toBe(1);
    expect(await prisma.documentSource.count({ where: { documentVersionId: upload.body.versionId as string } })).toBe(1);
    expect(await prisma.documentTag.count({ where: { documentId } })).toBe(0);
    const actions = await prisma.auditLog.findMany({ where: { actorUserId: user.userId }, select: { action: true } });
    expect(actions.map((row) => row.action)).toEqual(
      expect.arrayContaining(['WORKSPACE_SOURCE_LINKED', 'WORKSPACE_SOURCE_UNLINKED', 'TAG_DELETED', 'WORKSPACE_DELETED']),
    );
  });

  it('lets PostgreSQL reject cross-owner links and invalid source/version/document invariants when services are bypassed', async () => {
    const a = await identity('db-a');
    const b = await identity('db-b');
    const workspace = await prisma.workspace.create({ data: { ownerId: a.userId, name: 'A', normalizedName: 'a' } });
    const docA = await prisma.document.create({ data: { ownerId: a.userId, title: 'A' } });
    const docB = await prisma.document.create({ data: { ownerId: b.userId, title: 'B' } });
    const vA = await prisma.documentVersion.create({ data: { documentId: docA.id, versionNo: 1 } });
    const vB = await prisma.documentVersion.create({ data: { documentId: docB.id, versionNo: 1 } });

    await expect(prisma.workspaceSource.create({ data: { workspaceId: workspace.id, documentId: docB.id, ownerId: a.userId } })).rejects.toThrow();
    await expect(prisma.documentVersion.create({ data: { documentId: docA.id, versionNo: 0 } })).rejects.toThrow();
    await expect(
      prisma.documentSource.create({
        data: {
          documentVersionId: vA.id,
          stagingObjectKey: 'uploads/negative/source',
          objectKey: 'documents/negative/source',
          originalFilename: 'bad.txt',
          mediaType: 'text/plain',
          sizeBytes: BigInt(-1),
        },
      }),
    ).rejects.toThrow();
    await expect(prisma.document.update({ where: { id: docA.id }, data: { currentVersionId: vB.id } })).rejects.toThrow();
    await expect(prisma.document.update({ where: { id: docA.id }, data: { status: DocumentStatus.DELETED } })).rejects.toThrow();

    expect(await prisma.workspaceSource.count()).toBe(0);
    expect(await prisma.documentVersion.count({ where: { documentId: docA.id } })).toBe(1);
    expect(await prisma.documentSource.count({ where: { documentVersionId: vA.id } })).toBe(0);
    const persisted = await prisma.document.findUniqueOrThrow({ where: { id: docA.id } });
    expect(persisted.currentVersionId).toBeNull();
    expect(persisted.status).toBe(DocumentStatus.ACTIVE);
    expect(persisted.deletedAt).toBeNull();
  });
});
