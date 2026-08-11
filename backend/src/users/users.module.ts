import { Module } from '@nestjs/common';
import { SecurityModule } from '../auth/security.module';
import { UsersController } from './users.controller';
import { UsersService } from './users.service';

@Module({
  imports: [SecurityModule],
  controllers: [UsersController],
  providers: [UsersService],
  exports: [UsersService],
})
export class UsersModule {}
