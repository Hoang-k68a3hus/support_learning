import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import type { Workspace } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import type { CursorPage } from '../common/types/pagination';
import { normalizeOwnedName } from '../common/normalization/owned-name';
import { isUniqueConstraintError } from '../common/persistence/prisma-error';
import { PrismaService } from '../database/prisma.service';
import type { CreateWorkspaceDto, ListWorkspacesQueryDto, UpdateWorkspaceDto } from './dto/workspace.dto';

export interface WorkspaceDto {
  id: string;
  name: string;
  updatedAt: Date;
}

function toDto(workspace: Workspace): WorkspaceDto {
  return { id: workspace.id, name: workspace.name, updatedAt: workspace.updatedAt };
}

@Injectable()
export class WorkspacesService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  async create(ownerId: string, dto: CreateWorkspaceDto): Promise<WorkspaceDto> {
    try {
      const workspace = await this.prisma.workspace.create({
        data: { ownerId, name: dto.name, normalizedName: normalizeOwnedName(dto.name) },
      });
      return toDto(workspace);
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Workspace name is already in use');
      throw error;
    }
  }

  async list(ownerId: string, query: ListWorkspacesQueryDto): Promise<CursorPage<WorkspaceDto>> {
    if (query.cursor) await this.assertCursor(ownerId, query.cursor);
    const rows = await this.prisma.workspace.findMany({
      where: { ownerId, deletedAt: null },
      orderBy: [{ updatedAt: 'desc' }, { id: 'desc' }],
      take: query.limit + 1,
      ...(query.cursor ? { cursor: { id: query.cursor }, skip: 1 } : {}),
    });
    const hasMore = rows.length > query.limit;
    const page = hasMore ? rows.slice(0, query.limit) : rows;
    return { items: page.map(toDto), nextCursor: hasMore ? page.at(-1)?.id ?? null : null };
  }

  async get(ownerId: string, id: string): Promise<WorkspaceDto> {
    return toDto(await this.getOwnedActive(ownerId, id));
  }

  async update(ownerId: string, id: string, dto: UpdateWorkspaceDto): Promise<WorkspaceDto> {
    if (dto.name === undefined) throw new BadRequestException('At least one mutable field is required');
    await this.getOwnedActive(ownerId, id);
    try {
      const workspace = await this.prisma.workspace.update({
        where: { id },
        data: { name: dto.name, normalizedName: normalizeOwnedName(dto.name) },
      });
      return toDto(workspace);
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Workspace name is already in use');
      throw error;
    }
  }

  async delete(ownerId: string, id: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const workspace = await tx.workspace.findFirst({ where: { id, ownerId, deletedAt: null } });
      if (!workspace) throw new NotFoundException('Workspace not found');
      await tx.workspaceSource.deleteMany({ where: { workspaceId: id, ownerId } });
      await tx.workspace.update({ where: { id }, data: { deletedAt: new Date() } });
      await this.audit.append(tx, {
        actorUserId: ownerId,
        action: 'WORKSPACE_DELETED',
        resourceType: 'Workspace',
        resourceId: id,
        requestId,
      });
    });
  }

  async linkSource(ownerId: string, workspaceId: string, documentId: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const [workspace, document] = await Promise.all([
        tx.workspace.findFirst({ where: { id: workspaceId, ownerId, deletedAt: null }, select: { id: true } }),
        tx.document.findFirst({ where: { id: documentId, ownerId, deletedAt: null, status: 'ACTIVE' }, select: { id: true } }),
      ]);
      if (!workspace || !document) throw new NotFoundException('Workspace or document not found');
      const result = await tx.workspaceSource.createMany({
        data: [{ workspaceId, documentId, ownerId }],
        skipDuplicates: true,
      });
      if (result.count === 1) {
        await this.audit.append(tx, {
          actorUserId: ownerId,
          action: 'WORKSPACE_SOURCE_LINKED',
          resourceType: 'Workspace',
          resourceId: workspaceId,
          requestId,
          metadata: { documentId },
        });
      }
    });
  }

  async unlinkSource(ownerId: string, workspaceId: string, documentId: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const workspace = await tx.workspace.findFirst({ where: { id: workspaceId, ownerId, deletedAt: null }, select: { id: true } });
      if (!workspace) throw new NotFoundException('Workspace not found');
      const result = await tx.workspaceSource.deleteMany({ where: { workspaceId, documentId, ownerId } });
      if (result.count === 1) {
        await this.audit.append(tx, {
          actorUserId: ownerId,
          action: 'WORKSPACE_SOURCE_UNLINKED',
          resourceType: 'Workspace',
          resourceId: workspaceId,
          requestId,
          metadata: { documentId },
        });
      }
    });
  }

  private async getOwnedActive(ownerId: string, id: string): Promise<Workspace> {
    const workspace = await this.prisma.workspace.findFirst({ where: { id, ownerId, deletedAt: null } });
    if (!workspace) throw new NotFoundException('Workspace not found');
    return workspace;
  }

  private async assertCursor(ownerId: string, cursor: string): Promise<void> {
    const row = await this.prisma.workspace.findFirst({ where: { id: cursor, ownerId, deletedAt: null }, select: { id: true } });
    if (!row) throw new BadRequestException('Invalid workspace cursor');
  }
}
