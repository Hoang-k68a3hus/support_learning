import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import { CreateFolderDto, ListFoldersQueryDto, UpdateFolderDto } from './dto/folder.dto';
import { FoldersService } from './folders.service';

@Controller('folders')
@UseGuards(JwtAuthGuard)
export class FoldersController {
  constructor(private readonly folders: FoldersService) {}

  @Post()
  create(@CurrentUser() principal: AuthPrincipal, @Body() dto: CreateFolderDto) {
    return this.folders.create(principal.userId, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListFoldersQueryDto) {
    return this.folders.list(principal.userId, query);
  }

  @Patch(':id')
  update(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Body() dto: UpdateFolderDto,
    @Req() request: RequestContext,
  ) {
    return this.folders.update(principal.userId, id, dto, request.requestId);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext) {
    return this.folders.delete(principal.userId, id, request.requestId);
  }
}
