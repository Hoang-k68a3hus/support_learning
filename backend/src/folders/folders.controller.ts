import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import type { CursorPage } from '../common/types/pagination';
import { CreateFolderDto, ListFoldersQueryDto, UpdateFolderDto } from './dto/folder.dto';
import { FoldersService, type FolderDto } from './folders.service';

@Controller('folders')
@UseGuards(JwtAuthGuard)
export class FoldersController {
  constructor(private readonly folders: FoldersService) {}

  @Post()
  create(@CurrentUser() principal: AuthPrincipal, @Body() dto: CreateFolderDto): Promise<FolderDto> {
    return this.folders.create(principal.userId, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListFoldersQueryDto): Promise<CursorPage<FolderDto>> {
    return this.folders.list(principal.userId, query);
  }

  @Patch(':id')
  update(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Body() dto: UpdateFolderDto,
    @Req() request: RequestContext,
  ): Promise<FolderDto> {
    return this.folders.update(principal.userId, id, dto, request.requestId);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext): Promise<void> {
    return this.folders.delete(principal.userId, id, request.requestId);
  }
}
