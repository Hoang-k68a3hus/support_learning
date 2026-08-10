import type { ExecutionContext } from '@nestjs/common';
import { ForbiddenException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { Role } from '@prisma/client';
import { RolesGuard } from '../../src/auth/guards/roles.guard';
import type { RequestContext } from '../../src/common/types/http-request';

function contextWithRole(role?: Role): ExecutionContext {
  const request = {
    user: role ? { userId: 'u1', sessionId: 's1', role } : undefined,
  } as RequestContext;
  return {
    switchToHttp: () => ({ getRequest: () => request }),
    getHandler: () => function handler(): void {},
    getClass: () => class TestController {},
  } as unknown as ExecutionContext;
}

describe('RolesGuard', () => {
  it('allows routes without role metadata', () => {
    const reflector = { getAllAndOverride: jest.fn().mockReturnValue(undefined) } as unknown as Reflector;
    expect(new RolesGuard(reflector).canActivate(contextWithRole(Role.STUDENT))).toBe(true);
  });

  it('allows STUDENT for a STUDENT policy', () => {
    const reflector = { getAllAndOverride: jest.fn().mockReturnValue([Role.STUDENT]) } as unknown as Reflector;
    expect(new RolesGuard(reflector).canActivate(contextWithRole(Role.STUDENT))).toBe(true);
  });

  it('blocks STUDENT and allows ADMIN for ADMIN-only policy', () => {
    const reflector = { getAllAndOverride: jest.fn().mockReturnValue([Role.ADMIN]) } as unknown as Reflector;
    const guard = new RolesGuard(reflector);

    expect(() => guard.canActivate(contextWithRole(Role.STUDENT))).toThrow(ForbiddenException);
    expect(guard.canActivate(contextWithRole(Role.ADMIN))).toBe(true);
    expect(() => guard.canActivate(contextWithRole())).toThrow(ForbiddenException);
  });
});
