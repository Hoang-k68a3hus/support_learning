import { createParamDecorator, type ExecutionContext } from '@nestjs/common';
import type { AuthPrincipal, RequestContext } from '../../common/types/http-request';

export const CurrentUser = createParamDecorator(
  (_data: unknown, context: ExecutionContext): AuthPrincipal | undefined =>
    context.switchToHttp().getRequest<RequestContext>().user,
);
