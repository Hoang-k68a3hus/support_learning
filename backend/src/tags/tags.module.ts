import { Module } from '@nestjs/common';
import { AuditModule } from '../audit/audit.module';
import { SecurityModule } from '../auth/security.module';
import { TagsController } from './tags.controller';
import { TagsService } from './tags.service';

@Module({
  imports: [SecurityModule, AuditModule],
  controllers: [TagsController],
  providers: [TagsService],
})
export class TagsModule {}
