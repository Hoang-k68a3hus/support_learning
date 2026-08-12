import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Patch, Post, Put, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import type { CursorPage } from '../common/types/pagination';
import { CreateWorkspaceDto, ListWorkspacesQueryDto, UpdateWorkspaceDto } from './dto/workspace.dto';
import { WorkspacesService, type WorkspaceDto } from './workspaces.service';

@Controller('workspaces')
@UseGuards(JwtAuthGuard)
export class WorkspacesController {
  constructor(private readonly workspaces: WorkspacesService) {}

  @Post()
  create(@CurrentUser() principal: AuthPrincipal, @Body() dto: CreateWorkspaceDto): Promise<WorkspaceDto> {
    return this.workspaces.create(principal.userId, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListWorkspacesQueryDto): Promise<CursorPage<WorkspaceDto>> {
    return this.workspaces.list(principal.userId, query);
  }

  @Get(':id')
  get(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string): Promise<WorkspaceDto> {
    return this.workspaces.get(principal.userId, id);
  }

  @Patch(':id')
  update(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Body() dto: UpdateWorkspaceDto): Promise<WorkspaceDto> {
    return this.workspaces.update(principal.userId, id, dto);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext): Promise<void> {
    return this.workspaces.delete(principal.userId, id, request.requestId);
  }

  @Put(':id/sources/:documentId')
  @HttpCode(HttpStatus.NO_CONTENT)
  linkSource(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Param('documentId') documentId: string,
    @Req() request: RequestContext,
  ): Promise<void> {
    return this.workspaces.linkSource(principal.userId, id, documentId, request.requestId);
  }

  @Delete(':id/sources/:documentId')
  @HttpCode(HttpStatus.NO_CONTENT)
  unlinkSource(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Param('documentId') documentId: string,
    @Req() request: RequestContext,
  ): Promise<void> {
    return this.workspaces.unlinkSource(principal.userId, id, documentId, request.requestId);
  }
}
