import { Module } from '@nestjs/common';
import { UsersModule } from '../users/users.module';
import { AuthController } from './auth.controller';
import { AuthService } from './auth.service';
import { PasswordService } from './password.service';
import { SecurityModule } from './security.module';

@Module({
  imports: [UsersModule, SecurityModule],
  controllers: [AuthController],
  providers: [AuthService, PasswordService],
  exports: [PasswordService],
})
export class AuthModule {}
