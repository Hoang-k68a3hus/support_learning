import { Body, Controller, Delete, Get, Headers, HttpCode, HttpStatus, Param, Patch, Post, Put, Query, Req, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import type { AuthPrincipal, RequestContext } from '../common/types/http-request';
import { DocumentUploadService } from './document-upload.service';
import { DocumentsService } from './documents.service';
import { InitUploadDto, ListDocumentsQueryDto, ListVersionsQueryDto, NewVersionInitUploadDto, UpdateDocumentDto } from './dto/document.dto';

@Controller('documents')
@UseGuards(JwtAuthGuard)
export class DocumentsController {
  constructor(
    private readonly documents: DocumentsService,
    private readonly uploads: DocumentUploadService,
  ) {}

  @Post('init-upload')
  initUpload(
    @CurrentUser() principal: AuthPrincipal,
    @Headers('idempotency-key') idempotencyKey: string | undefined,
    @Body() dto: InitUploadDto,
  ) {
    return this.uploads.initDocument(principal.userId, idempotencyKey, dto);
  }

  @Get()
  list(@CurrentUser() principal: AuthPrincipal, @Query() query: ListDocumentsQueryDto) {
    return this.documents.list(principal.userId, query);
  }

  @Get(':id')
  get(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string) {
    return this.documents.get(principal.userId, id);
  }

  @Patch(':id')
  update(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Body() dto: UpdateDocumentDto,
    @Req() request: RequestContext,
  ) {
    return this.documents.update(principal.userId, id, dto, request.requestId);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  delete(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Req() request: RequestContext) {
    return this.documents.delete(principal.userId, id, request.requestId);
  }

  @Get(':id/versions')
  versions(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string, @Query() query: ListVersionsQueryDto) {
    return this.documents.listVersions(principal.userId, id, query);
  }

  @Get(':id/status')
  status(@CurrentUser() principal: AuthPrincipal, @Param('id') id: string) {
    return this.documents.getStatus(principal.userId, id);
  }

  @Post(':documentId/versions/init-upload')
  initNewVersion(
    @CurrentUser() principal: AuthPrincipal,
    @Param('documentId') documentId: string,
    @Headers('idempotency-key') idempotencyKey: string | undefined,
    @Body() dto: NewVersionInitUploadDto,
  ) {
    return this.uploads.initNewVersion(principal.userId, documentId, idempotencyKey, dto);
  }

  @Post(':documentId/versions/:versionId/complete')
  @HttpCode(HttpStatus.OK)
  complete(
    @CurrentUser() principal: AuthPrincipal,
    @Param('documentId') documentId: string,
    @Param('versionId') versionId: string,
  ) {
    return this.uploads.complete(principal.userId, documentId, versionId);
  }

  @Put(':id/tags/:tagId')
  @HttpCode(HttpStatus.NO_CONTENT)
  linkTag(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Param('tagId') tagId: string,
    @Req() request: RequestContext,
  ) {
    return this.documents.linkTag(principal.userId, id, tagId, request.requestId);
  }

  @Delete(':id/tags/:tagId')
  @HttpCode(HttpStatus.NO_CONTENT)
  unlinkTag(
    @CurrentUser() principal: AuthPrincipal,
    @Param('id') id: string,
    @Param('tagId') tagId: string,
    @Req() request: RequestContext,
  ) {
    return this.documents.unlinkTag(principal.userId, id, tagId, request.requestId);
  }
}
