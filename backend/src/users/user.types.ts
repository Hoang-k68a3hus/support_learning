import type { Role } from '@prisma/client';

export interface PublicUser {
  id: string;
  email: string;
  fullName: string | null;
  role: Role;
  createdAt: Date;
  updatedAt: Date;
}
