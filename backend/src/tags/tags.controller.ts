import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import type { CursorPage } from '../common/types/pagination';
import { CreateTagDto, ListTagsQueryDto, UpdateTagDto } from './dto/tag.dto';
import { TagsService, type TagDto } from './tags.service';

@Controller('tags')
@UseGuards(JwtAuthGuard)
export class TagsController {
  constructor(private readonly tags: TagsService) {}

  @Post()
  create(@CurrentUser() principal: AuthPrincipal, @Body() dto: CreateTagDto): Promise<TagDto> {
    return this.tags.create(principal.userId, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListTagsQueryDto): Promise<CursorPage<TagDto>> {
    return this.tags.list(principal.userId, query);
  }

  @Patch(':id')
  update(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Body() dto: UpdateTagDto): Promise<TagDto> {
    return this.tags.update(principal.userId, id, dto);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext): Promise<void> {
    return this.tags.delete(principal.userId, id, request.requestId);
  }
}
