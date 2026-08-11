import {
  type CallHandler,
  type ExecutionContext,
  UnauthorizedException,
} from '@nestjs/common';
import type { Response } from 'express';
import { firstValueFrom, throwError } from 'rxjs';
import { JsonLoggerService } from '../../src/common/logging/json-logger.service';
import { RequestLoggingInterceptor } from '../../src/common/logging/request-logging.interceptor';
import type { RequestContext } from '../../src/common/types/http-request';

function createContext(request: RequestContext, response: Response): ExecutionContext {
  return {
    switchToHttp: () => ({
      getRequest: () => request,
      getResponse: () => response,
    }),
  } as unknown as ExecutionContext;
}

describe('RequestLoggingInterceptor', () => {
  it('logs the actual HttpException status even before the exception filter writes the response', async () => {
    const log = jest.fn();
    const logger = { log } as unknown as JsonLoggerService;
    const interceptor = new RequestLoggingInterceptor(logger);
    const request = {
      requestId: 'request-1',
      method: 'GET',
      originalUrl: '/api/v1/users/me?ignored=true',
    } as RequestContext;
    const response = { statusCode: 200 } as Response;
    const next = {
      handle: () => throwError(() => new UnauthorizedException('Authentication is required')),
    } as CallHandler;

    await expect(firstValueFrom(interceptor.intercept(createContext(request, response), next))).rejects.toBeInstanceOf(
      UnauthorizedException,
    );

    expect(log).toHaveBeenCalledWith(
      'http_request',
      expect.objectContaining({
        requestId: 'request-1',
        route: '/api/v1/users/me',
        status: 401,
      }),
    );
  });
});
