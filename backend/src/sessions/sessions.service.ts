import { Injectable, UnauthorizedException } from '@nestjs/common';
import type { Role, Session, User } from '@prisma/client';
import { PrismaService } from '../database/prisma.service';

export type SessionWithUser = Session & { user: User };

@Injectable()
export class SessionsService {
  constructor(private readonly prisma: PrismaService) {}

  create(input: {
    id: string;
    userId: string;
    refreshTokenHash: string;
    expiresAt: Date;
  }): Promise<Session> {
    return this.prisma.session.create({ data: input });
  }

  async getActiveWithUser(sessionId: string, userId: string, now = new Date()): Promise<SessionWithUser> {
    const session = await this.prisma.session.findFirst({
      where: {
        id: sessionId,
        userId,
        revokedAt: null,
        expiresAt: { gt: now },
      },
      include: { user: true },
    });
    if (!session) throw new UnauthorizedException('Session is not active');
    return session;
  }

  async assertActive(sessionId: string, userId: string, expectedRole: Role, now = new Date()): Promise<void> {
    const session = await this.getActiveWithUser(sessionId, userId, now);
    if (session.user.role !== expectedRole) {
      throw new UnauthorizedException('Authentication context is stale');
    }
  }

  async rotate(input: {
    sessionId: string;
    userId: string;
    expectedRefreshTokenHash: string;
    nextRefreshTokenHash: string;
    nextExpiresAt: Date;
    now?: Date;
  }): Promise<void> {
    const now = input.now ?? new Date();
    const result = await this.prisma.session.updateMany({
      where: {
        id: input.sessionId,
        userId: input.userId,
        refreshTokenHash: input.expectedRefreshTokenHash,
        revokedAt: null,
        expiresAt: { gt: now },
      },
      data: {
        refreshTokenHash: input.nextRefreshTokenHash,
        expiresAt: input.nextExpiresAt,
        lastUsedAt: now,
      },
    });

    if (result.count !== 1) {
      throw new UnauthorizedException('Refresh token is no longer valid');
    }
  }

  async revoke(sessionId: string, userId: string, now = new Date()): Promise<void> {
    await this.prisma.session.updateMany({
      where: { id: sessionId, userId, revokedAt: null },
      data: { revokedAt: now },
    });
  }
}
