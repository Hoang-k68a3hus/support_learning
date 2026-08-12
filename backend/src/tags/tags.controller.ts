import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import { CreateTagDto, ListTagsQueryDto, UpdateTagDto } from './dto/tag.dto';
import { TagsService } from './tags.service';

@Controller('tags')
@UseGuards(JwtAuthGuard)
export class TagsController {
  constructor(private readonly tags: TagsService) {}

  @Post()
  create(@CurrentUser() principal: AuthPrincipal, @Body() dto: CreateTagDto) {
    return this.tags.create(principal.userId, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListTagsQueryDto) {
    return this.tags.list(principal.userId, query);
  }

  @Patch(':id')
  update(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Body() dto: UpdateTagDto) {
    return this.tags.update(principal.userId, id, dto);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext) {
    return this.tags.delete(principal.userId, id, request.requestId);
  }
}
