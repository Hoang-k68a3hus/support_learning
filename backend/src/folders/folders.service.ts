import { BadRequestException, ConflictException, Injectable, NotFoundException, UnprocessableEntityException } from '@nestjs/common';
import type { Folder } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import { normalizeOwnedName } from '../common/normalization/owned-name';
import { isUniqueConstraintError } from '../common/persistence/prisma-error';
import type { CursorPage } from '../common/types/pagination';
import { PrismaService } from '../database/prisma.service';
import type { CreateFolderDto, ListFoldersQueryDto, UpdateFolderDto } from './dto/folder.dto';

export interface FolderDto {
  id: string;
  parentId: string | null;
  name: string;
  updatedAt: Date;
}

function toDto(folder: Folder): FolderDto {
  return { id: folder.id, parentId: folder.parentId, name: folder.name, updatedAt: folder.updatedAt };
}

@Injectable()
export class FoldersService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  async create(ownerId: string, dto: CreateFolderDto): Promise<FolderDto> {
    if (dto.parentId) await this.getOwnedActive(ownerId, dto.parentId);
    try {
      return toDto(
        await this.prisma.folder.create({
          data: { ownerId, parentId: dto.parentId ?? null, name: dto.name, normalizedName: normalizeOwnedName(dto.name) },
        }),
      );
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Folder name is already in use for this parent');
      throw error;
    }
  }

  async list(ownerId: string, query: ListFoldersQueryDto): Promise<CursorPage<FolderDto>> {
    const parentId = query.parentId ?? null;
    if (query.parentId) await this.getOwnedActive(ownerId, query.parentId);
    if (query.cursor) await this.assertCursor(ownerId, query.cursor, parentId);
    const rows = await this.prisma.folder.findMany({
      where: { ownerId, parentId, deletedAt: null },
      orderBy: [{ normalizedName: 'asc' }, { id: 'asc' }],
      take: query.limit + 1,
      ...(query.cursor ? { cursor: { id: query.cursor }, skip: 1 } : {}),
    });
    const hasMore = rows.length > query.limit;
    const page = hasMore ? rows.slice(0, query.limit) : rows;
    return { items: page.map(toDto), nextCursor: hasMore ? page.at(-1)?.id ?? null : null };
  }

  async update(ownerId: string, id: string, dto: UpdateFolderDto, requestId: string): Promise<FolderDto> {
    if (dto.name === undefined && dto.parentId === undefined) throw new BadRequestException('At least one mutable field is required');
    const folder = await this.getOwnedActive(ownerId, id);
    const nextParentId = dto.parentId === undefined ? folder.parentId : dto.parentId;
    if (nextParentId === id) throw new UnprocessableEntityException('Folder cannot be its own parent');
    if (nextParentId) {
      await this.getOwnedActive(ownerId, nextParentId);
      await this.assertNoCycle(ownerId, id, nextParentId);
    }

    try {
      return await this.prisma.$transaction(async (tx) => {
        const updated = await tx.folder.update({
          where: { id },
          data: {
            ...(dto.name !== undefined ? { name: dto.name, normalizedName: normalizeOwnedName(dto.name) } : {}),
            ...(dto.parentId !== undefined ? { parentId: dto.parentId } : {}),
          },
        });
        if (folder.parentId !== updated.parentId) {
          await this.audit.append(tx, {
            actorUserId: ownerId,
            action: 'FOLDER_MOVED',
            resourceType: 'Folder',
            resourceId: id,
            requestId,
            metadata: { fromParentId: folder.parentId, toParentId: updated.parentId },
          });
        }
        return toDto(updated);
      });
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Folder name is already in use for this parent');
      throw error;
    }
  }

  async delete(ownerId: string, id: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const folder = await tx.folder.findFirst({ where: { id, ownerId, deletedAt: null } });
      if (!folder) throw new NotFoundException('Folder not found');
      const [childCount, documentCount] = await Promise.all([
        tx.folder.count({ where: { ownerId, parentId: id, deletedAt: null } }),
        tx.document.count({ where: { ownerId, folderId: id, deletedAt: null, status: 'ACTIVE' } }),
      ]);
      if (childCount > 0 || documentCount > 0) throw new ConflictException('Folder must be empty before deletion');
      await tx.folder.update({ where: { id }, data: { deletedAt: new Date() } });
      await this.audit.append(tx, {
        actorUserId: ownerId,
        action: 'FOLDER_DELETED',
        resourceType: 'Folder',
        resourceId: id,
        requestId,
      });
    });
  }

  private async getOwnedActive(ownerId: string, id: string): Promise<Folder> {
    const folder = await this.prisma.folder.findFirst({ where: { id, ownerId, deletedAt: null } });
    if (!folder) throw new NotFoundException('Folder not found');
    return folder;
  }

  private async assertNoCycle(ownerId: string, movingFolderId: string, proposedParentId: string): Promise<void> {
    const visited = new Set<string>();
    let cursor: string | null = proposedParentId;
    while (cursor) {
      if (cursor === movingFolderId) throw new UnprocessableEntityException('Folder move would create a cycle');
      if (visited.has(cursor)) throw new UnprocessableEntityException('Existing folder hierarchy contains a cycle');
      visited.add(cursor);
      const parent = await this.prisma.folder.findFirst({
        where: { id: cursor, ownerId, deletedAt: null },
        select: { parentId: true },
      });
      if (!parent) throw new NotFoundException('Parent folder not found');
      cursor = parent.parentId;
    }
  }

  private async assertCursor(ownerId: string, cursor: string, parentId: string | null): Promise<void> {
    const row = await this.prisma.folder.findFirst({ where: { id: cursor, ownerId, parentId, deletedAt: null }, select: { id: true } });
    if (!row) throw new BadRequestException('Invalid folder cursor');
  }
}
