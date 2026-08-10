import { ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { Prisma, Role, type User } from '@prisma/client';
import { PrismaService } from '../database/prisma.service';
import type { PublicUser } from './user.types';

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

@Injectable()
export class UsersService {
  constructor(private readonly prisma: PrismaService) {}

  async createStudent(input: {
    email: string;
    passwordHash: string;
    fullName?: string;
  }): Promise<PublicUser> {
    try {
      const user = await this.prisma.user.create({
        data: {
          email: normalizeEmail(input.email),
          passwordHash: input.passwordHash,
          fullName: input.fullName?.trim() || null,
          role: Role.STUDENT,
        },
      });
      return this.toPublicUser(user);
    } catch (error) {
      if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002') {
        throw new ConflictException('An account with this email already exists');
      }
      throw error;
    }
  }

  findByEmailForAuthentication(email: string): Promise<User | null> {
    return this.prisma.user.findUnique({ where: { email: normalizeEmail(email) } });
  }

  async getPublicById(id: string): Promise<PublicUser> {
    const user = await this.prisma.user.findUnique({ where: { id } });
    if (!user) throw new NotFoundException('User not found');
    return this.toPublicUser(user);
  }

  toPublicUser(user: User): PublicUser {
    return {
      id: user.id,
      email: user.email,
      fullName: user.fullName,
      role: user.role,
      createdAt: user.createdAt,
      updatedAt: user.updatedAt,
    };
  }
}
