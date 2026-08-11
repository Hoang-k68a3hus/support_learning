import type { Request } from 'express';
import type { Role } from '@prisma/client';

export interface AuthPrincipal {
  userId: string;
  sessionId: string;
  role: Role;
}

export interface RequestContext extends Request {
  requestId: string;
  user?: AuthPrincipal;
}
