import { Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import type { Role } from '@prisma/client';
import { createHash, randomUUID } from 'node:crypto';
import { AppConfigService } from '../config/app-config.service';

interface AccessClaims {
  sub: string;
  sid: string;
  role: Role;
  type: 'access';
  iat?: number;
  exp?: number;
}

interface RefreshClaims {
  sub: string;
  sid: string;
  jti: string;
  type: 'refresh';
  iat?: number;
  exp?: number;
}

export interface IssuedRefreshToken {
  token: string;
  hash: string;
  expiresAt: Date;
}

@Injectable()
export class TokenService {
  constructor(
    private readonly jwt: JwtService,
    private readonly config: AppConfigService,
  ) {}

  issueAccessToken(userId: string, sessionId: string, role: Role): Promise<string> {
    const claims: AccessClaims = { sub: userId, sid: sessionId, role, type: 'access' };
    return this.jwt.signAsync(claims, {
      secret: this.config.jwtAccessSecret,
      expiresIn: this.config.jwtAccessTtlSeconds,
      algorithm: 'HS256',
    });
  }

  async issueRefreshToken(userId: string, sessionId: string, now = new Date()): Promise<IssuedRefreshToken> {
    const claims: RefreshClaims = {
      sub: userId,
      sid: sessionId,
      jti: randomUUID(),
      type: 'refresh',
    };
    const token = await this.jwt.signAsync(claims, {
      secret: this.config.jwtRefreshSecret,
      expiresIn: this.config.jwtRefreshTtlSeconds,
      algorithm: 'HS256',
    });
    return {
      token,
      hash: this.hashRefreshToken(token),
      expiresAt: new Date(now.getTime() + this.config.jwtRefreshTtlSeconds * 1000),
    };
  }

  async verifyAccessToken(token: string): Promise<AccessClaims> {
    try {
      const claims = await this.jwt.verifyAsync<AccessClaims>(token, {
        secret: this.config.jwtAccessSecret,
        algorithms: ['HS256'],
      });
      if (claims.type !== 'access' || !claims.sub || !claims.sid || !claims.role) {
        throw new UnauthorizedException('Invalid access token');
      }
      return claims;
    } catch (error) {
      if (error instanceof UnauthorizedException) throw error;
      throw new UnauthorizedException('Invalid access token');
    }
  }

  async verifyRefreshToken(token: string): Promise<RefreshClaims> {
    try {
      const claims = await this.jwt.verifyAsync<RefreshClaims>(token, {
        secret: this.config.jwtRefreshSecret,
        algorithms: ['HS256'],
      });
      if (claims.type !== 'refresh' || !claims.sub || !claims.sid || !claims.jti) {
        throw new UnauthorizedException('Invalid refresh token');
      }
      return claims;
    } catch (error) {
      if (error instanceof UnauthorizedException) throw error;
      throw new UnauthorizedException('Invalid refresh token');
    }
  }

  hashRefreshToken(token: string): string {
    return createHash('sha256').update(token).digest('hex');
  }
}
