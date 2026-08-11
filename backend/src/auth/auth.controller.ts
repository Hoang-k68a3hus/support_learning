import {
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  Post,
  Req,
  Res,
  UnauthorizedException,
  UseGuards,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { AppConfigService } from '../config/app-config.service';
import type { AuthPrincipal } from '../common/types/http-request';
import { RegisterDto } from '../users/dto/register.dto';
import type { PublicUser } from '../users/user.types';
import { CurrentUser } from './decorators/current-user.decorator';
import { LoginDto } from './dto/login.dto';
import { JwtAuthGuard } from './guards/jwt-auth.guard';
import { AuthService } from './auth.service';

const REFRESH_COOKIE = 'refresh_token';

@Controller('auth')
export class AuthController {
  constructor(
    private readonly auth: AuthService,
    private readonly config: AppConfigService,
  ) {}

  @Post('register')
  async register(@Body() dto: RegisterDto): Promise<{ user: PublicUser }> {
    return { user: await this.auth.register(dto) };
  }

  @Post('login')
  @HttpCode(HttpStatus.OK)
  async login(
    @Body() dto: LoginDto,
    @Res({ passthrough: true }) response: Response,
  ): Promise<{ user: PublicUser; accessToken: string }> {
    const result = await this.auth.login(dto);
    this.setRefreshCookie(response, result.refreshToken.token);
    return { user: result.user, accessToken: result.accessToken };
  }

  @Post('refresh')
  @HttpCode(HttpStatus.OK)
  async refresh(
    @Req() request: Request,
    @Res({ passthrough: true }) response: Response,
  ): Promise<{ accessToken: string }> {
    const rawRefreshToken = this.readRefreshCookie(request);
    const result = await this.auth.refresh(rawRefreshToken);
    this.setRefreshCookie(response, result.refreshToken.token);
    return { accessToken: result.accessToken };
  }

  @Post('logout')
  @UseGuards(JwtAuthGuard)
  @HttpCode(HttpStatus.NO_CONTENT)
  async logout(
    @CurrentUser() principal: AuthPrincipal,
    @Res({ passthrough: true }) response: Response,
  ): Promise<void> {
    await this.auth.logout(principal.userId, principal.sessionId);
    response.clearCookie(REFRESH_COOKIE, this.cookieOptions());
  }

  private readRefreshCookie(request: Request): string {
    const cookies = request.cookies as Record<string, unknown>;
    const token = cookies[REFRESH_COOKIE];
    if (typeof token !== 'string' || token.length === 0) {
      throw new UnauthorizedException('Refresh token is required');
    }
    return token;
  }

  private setRefreshCookie(response: Response, token: string): void {
    response.cookie(REFRESH_COOKIE, token, {
      ...this.cookieOptions(),
      maxAge: this.config.jwtRefreshTtlSeconds * 1000,
    });
  }

  private cookieOptions(): {
    httpOnly: true;
    secure: boolean;
    sameSite: 'lax';
    path: string;
  } {
    return {
      httpOnly: true,
      secure: this.config.isProduction,
      sameSite: 'lax',
      path: '/api/v1/auth',
    };
  }
}
