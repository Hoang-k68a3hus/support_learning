import {
  CallHandler,
  ExecutionContext,
  Injectable,
  NestInterceptor,
} from '@nestjs/common';
import type { Response } from 'express';
import { Observable } from 'rxjs';
import { finalize } from 'rxjs/operators';
import type { RequestContext } from '../types/http-request';
import { JsonLoggerService } from './json-logger.service';

@Injectable()
export class RequestLoggingInterceptor implements NestInterceptor {
  constructor(private readonly logger: JsonLoggerService) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const http = context.switchToHttp();
    const request = http.getRequest<RequestContext>();
    const response = http.getResponse<Response>();
    const started = process.hrtime.bigint();

    return next.handle().pipe(
      finalize(() => {
        const latencyMs = Number(process.hrtime.bigint() - started) / 1_000_000;
        this.logger.log('http_request', {
          requestId: request.requestId,
          method: request.method,
          route: request.originalUrl.split('?')[0],
          status: response.statusCode,
          latencyMs: Math.round(latencyMs * 100) / 100,
          userId: request.user?.userId,
        });
      }),
    );
  }
}
