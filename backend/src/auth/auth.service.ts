import { Injectable, UnauthorizedException } from '@nestjs/common';
import { UserStatus } from '@prisma/client';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { SessionsService } from '../sessions/sessions.service';
import type { PublicUser } from '../users/user.types';
import { UsersService } from '../users/users.service';
import type { LoginDto } from './dto/login.dto';
import type { RegisterDto } from '../users/dto/register.dto';
import { PasswordService } from './password.service';
import { TokenService, type IssuedRefreshToken } from './token.service';

export interface LoginResult {
  user: PublicUser;
  accessToken: string;
  refreshToken: IssuedRefreshToken;
}

export interface RefreshResult {
  accessToken: string;
  refreshToken: IssuedRefreshToken;
}

@Injectable()
export class AuthService {
  constructor(
    private readonly users: UsersService,
    private readonly passwords: PasswordService,
    private readonly tokens: TokenService,
    private readonly sessions: SessionsService,
  ) {}

  async register(dto: RegisterDto): Promise<PublicUser> {
    const passwordHash = await this.passwords.hash(dto.password);
    return this.users.createStudent({ email: dto.email, passwordHash });
  }

  async login(dto: LoginDto): Promise<LoginResult> {
    const user = await this.users.findByEmailForAuthentication(dto.email);
    const passwordValid = await this.passwords.verifyForAuthentication(user?.passwordHash ?? null, dto.password);
    if (!user || !passwordValid || user.status !== UserStatus.ACTIVE) {
      throw new UnauthorizedException('Invalid email or password');
    }

    const sessionId = randomUUID();
    const refreshToken = await this.tokens.issueRefreshToken(user.id, sessionId);
    const accessToken = await this.tokens.issueAccessToken(user.id, sessionId, user.role);

    await this.sessions.create({
      id: sessionId,
      userId: user.id,
      refreshTokenHash: refreshToken.hash,
      expiresAt: refreshToken.expiresAt,
    });

    return {
      user: this.users.toPublicUser(user),
      accessToken,
      refreshToken,
    };
  }

  async refresh(rawRefreshToken: string): Promise<RefreshResult> {
    const claims = await this.tokens.verifyRefreshToken(rawRefreshToken);
    const session = await this.sessions.getActiveWithUser(claims.sid, claims.sub);
    const presentedHash = this.tokens.hashRefreshToken(rawRefreshToken);

    if (!this.hashesMatch(session.refreshTokenHash, presentedHash)) {
      throw new UnauthorizedException('Refresh token is no longer valid');
    }

    const nextRefreshToken = await this.tokens.issueRefreshToken(session.userId, session.id);
    const accessToken = await this.tokens.issueAccessToken(session.userId, session.id, session.user.role);

    await this.sessions.rotate({
      sessionId: session.id,
      userId: session.userId,
      expectedRefreshTokenHash: presentedHash,
      expectedRotationVersion: session.rotationVersion,
      nextRefreshTokenHash: nextRefreshToken.hash,
      nextExpiresAt: nextRefreshToken.expiresAt,
    });

    return { accessToken, refreshToken: nextRefreshToken };
  }

  logout(userId: string, sessionId: string): Promise<void> {
    return this.sessions.revoke(sessionId, userId);
  }

  private hashesMatch(storedHash: string, presentedHash: string): boolean {
    const stored = Buffer.from(storedHash, 'hex');
    const presented = Buffer.from(presentedHash, 'hex');
    return stored.length === presented.length && timingSafeEqual(stored, presented);
  }
}
