import type { Role, UserStatus } from '@prisma/client';

export interface PublicUser {
  id: string;
  email: string;
  fullName: string | null;
  role: Role;
  status: UserStatus;
  createdAt: Date;
  updatedAt: Date;
}
