import { Module } from '@nestjs/common';
import { JwtModule } from '@nestjs/jwt';
import { SessionsModule } from '../sessions/sessions.module';
import { JwtAuthGuard } from './guards/jwt-auth.guard';
import { RolesGuard } from './guards/roles.guard';
import { TokenService } from './token.service';

@Module({
  imports: [JwtModule.register({}), SessionsModule],
  providers: [TokenService, JwtAuthGuard, RolesGuard],
  exports: [TokenService, JwtAuthGuard, RolesGuard, SessionsModule],
})
export class SecurityModule {}
