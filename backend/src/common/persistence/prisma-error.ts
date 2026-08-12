import { Prisma } from '@prisma/client';

export function isPrismaKnownError(error: unknown, code: string): boolean {
  return error instanceof Prisma.PrismaClientKnownRequestError && error.code === code;
}

export function isUniqueConstraintError(error: unknown): boolean {
  return isPrismaKnownError(error, 'P2002');
}
