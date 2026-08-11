import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import type { RequestContext } from '../../common/types/http-request';
import { SessionsService } from '../../sessions/sessions.service';
import { TokenService } from '../token.service';

@Injectable()
export class JwtAuthGuard implements CanActivate {
  constructor(
    private readonly tokens: TokenService,
    private readonly sessions: SessionsService,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<RequestContext>();
    const authorization = request.header('authorization');
    if (!authorization) throw new UnauthorizedException('Authentication is required');

    const [scheme, token, extra] = authorization.split(' ');
    if (scheme !== 'Bearer' || !token || extra) {
      throw new UnauthorizedException('Malformed Authorization header');
    }

    const claims = await this.tokens.verifyAccessToken(token);
    await this.sessions.assertActive(claims.sid, claims.sub, claims.role);
    request.user = { userId: claims.sub, sessionId: claims.sid, role: claims.role };
    return true;
  }
}
