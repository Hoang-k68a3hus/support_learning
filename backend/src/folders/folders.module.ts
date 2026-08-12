import { Module } from '@nestjs/common';
import { AuditModule } from '../audit/audit.module';
import { SecurityModule } from '../auth/security.module';
import { FoldersController } from './folders.controller';
import { FoldersService } from './folders.service';

@Module({
  imports: [SecurityModule, AuditModule],
  controllers: [FoldersController],
  providers: [FoldersService],
})
export class FoldersModule {}
