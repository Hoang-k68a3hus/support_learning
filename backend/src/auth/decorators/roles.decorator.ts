import { SetMetadata } from '@nestjs/common';
import type { Role } from '@prisma/client';

export const ROLES_KEY = 'required_roles';
export const Roles = (...roles: Role[]) => SetMetadata(ROLES_KEY, roles);
