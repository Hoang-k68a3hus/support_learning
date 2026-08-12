import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import type { Tag } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import { normalizeOwnedName } from '../common/normalization/owned-name';
import { isUniqueConstraintError } from '../common/persistence/prisma-error';
import type { CursorPage } from '../common/types/pagination';
import { PrismaService } from '../database/prisma.service';
import type { CreateTagDto, ListTagsQueryDto, UpdateTagDto } from './dto/tag.dto';

export interface TagDto {
  id: string;
  name: string;
}

function toDto(tag: Tag): TagDto {
  return { id: tag.id, name: tag.name };
}

@Injectable()
export class TagsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  async create(ownerId: string, dto: CreateTagDto): Promise<TagDto> {
    try {
      return toDto(await this.prisma.tag.create({ data: { ownerId, name: dto.name, normalizedName: normalizeOwnedName(dto.name) } }));
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Tag name is already in use');
      throw error;
    }
  }

  async list(ownerId: string, query: ListTagsQueryDto): Promise<CursorPage<TagDto>> {
    if (query.cursor) {
      const cursor = await this.prisma.tag.findFirst({ where: { id: query.cursor, ownerId }, select: { id: true } });
      if (!cursor) throw new BadRequestException('Invalid tag cursor');
    }
    const rows = await this.prisma.tag.findMany({
      where: { ownerId },
      orderBy: [{ normalizedName: 'asc' }, { id: 'asc' }],
      take: query.limit + 1,
      ...(query.cursor ? { cursor: { id: query.cursor }, skip: 1 } : {}),
    });
    const hasMore = rows.length > query.limit;
    const page = hasMore ? rows.slice(0, query.limit) : rows;
    return { items: page.map(toDto), nextCursor: hasMore ? page.at(-1)?.id ?? null : null };
  }

  async update(ownerId: string, id: string, dto: UpdateTagDto): Promise<TagDto> {
    if (dto.name === undefined) throw new BadRequestException('At least one mutable field is required');
    await this.getOwned(ownerId, id);
    try {
      return toDto(
        await this.prisma.tag.update({
          where: { id },
          data: { name: dto.name, normalizedName: normalizeOwnedName(dto.name) },
        }),
      );
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new ConflictException('Tag name is already in use');
      throw error;
    }
  }

  async delete(ownerId: string, id: string, requestId: string): Promise<void> {
    await this.prisma.$transaction(async (tx) => {
      const tag = await tx.tag.findFirst({ where: { id, ownerId } });
      if (!tag) throw new NotFoundException('Tag not found');
      await tx.documentTag.deleteMany({ where: { tagId: id, ownerId } });
      await tx.tag.delete({ where: { id } });
      await this.audit.append(tx, {
        actorUserId: ownerId,
        action: 'TAG_DELETED',
        resourceType: 'Tag',
        resourceId: id,
        requestId,
      });
    });
  }

  private async getOwned(ownerId: string, id: string): Promise<Tag> {
    const tag = await this.prisma.tag.findFirst({ where: { id, ownerId } });
    if (!tag) throw new NotFoundException('Tag not found');
    return tag;
  }
}
