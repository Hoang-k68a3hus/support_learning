import { Module } from '@nestjs/common';
import { SecurityModule } from '../auth/security.module';
import { AuditModule } from '../audit/audit.module';
import { WorkspacesController } from './workspaces.controller';
import { WorkspacesService } from './workspaces.service';

@Module({
  imports: [SecurityModule, AuditModule],
  controllers: [WorkspacesController],
  providers: [WorkspacesService],
})
export class WorkspacesModule {}
