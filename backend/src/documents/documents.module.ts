import { Module } from '@nestjs/common';
import { AuditModule } from '../audit/audit.module';
import { SecurityModule } from '../auth/security.module';
import { IdempotencyModule } from '../idempotency/idempotency.module';
import { OutboxModule } from '../outbox/outbox.module';
import { StorageModule } from '../storage/storage.module';
import { DocumentUploadService } from './document-upload.service';
import { DocumentsController } from './documents.controller';
import { DocumentsService } from './documents.service';

@Module({
  imports: [SecurityModule, AuditModule, IdempotencyModule, OutboxModule, StorageModule],
  controllers: [DocumentsController],
  providers: [DocumentsService, DocumentUploadService],
})
export class DocumentsModule {}
