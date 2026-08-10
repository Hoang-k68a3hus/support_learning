import {
  ArgumentsHost,
  Catch,
  HttpException,
  HttpStatus,
  type ExceptionFilter,
} from '@nestjs/common';
import type { Response } from 'express';
import type { RequestContext } from '../types/http-request';
import { JsonLoggerService } from '../logging/json-logger.service';

interface ErrorBody {
  error: {
    code: string;
    message: string;
    details?: string[];
  };
  requestId: string;
  path: string;
  timestamp: string;
}

const STATUS_CODES: Partial<Record<number, string>> = {
  [HttpStatus.BAD_REQUEST]: 'VALIDATION_ERROR',
  [HttpStatus.UNAUTHORIZED]: 'AUTHENTICATION_ERROR',
  [HttpStatus.FORBIDDEN]: 'AUTHORIZATION_ERROR',
  [HttpStatus.NOT_FOUND]: 'NOT_FOUND',
  [HttpStatus.CONFLICT]: 'CONFLICT',
  [HttpStatus.UNPROCESSABLE_ENTITY]: 'BUSINESS_INVARIANT_VIOLATION',
  [HttpStatus.SERVICE_UNAVAILABLE]: 'DEPENDENCY_UNAVAILABLE',
};

@Catch()
export class HttpExceptionFilter implements ExceptionFilter {
  constructor(private readonly logger: JsonLoggerService) {}

  catch(exception: unknown, host: ArgumentsHost): void {
    const http = host.switchToHttp();
    const request = http.getRequest<RequestContext>();
    const response = http.getResponse<Response>();
    const isHttp = exception instanceof HttpException;
    const status = isHttp ? exception.getStatus() : HttpStatus.INTERNAL_SERVER_ERROR;
    const code = STATUS_CODES[status] ?? 'INTERNAL_ERROR';

    let message = status === HttpStatus.INTERNAL_SERVER_ERROR ? 'Internal server error' : 'Request failed';
    let details: string[] | undefined;

    if (isHttp) {
      const exceptionResponse = exception.getResponse();
      if (typeof exceptionResponse === 'string') {
        message = exceptionResponse;
      } else if (typeof exceptionResponse === 'object' && exceptionResponse !== null) {
        const value = exceptionResponse as { message?: string | string[] };
        if (Array.isArray(value.message)) {
          message = 'Request validation failed';
          details = value.message;
        } else if (typeof value.message === 'string') {
          message = value.message;
        }
      }
    }

    if (status >= HttpStatus.INTERNAL_SERVER_ERROR) {
      this.logger.error('http_exception', {
        requestId: request.requestId,
        method: request.method,
        route: request.originalUrl.split('?')[0],
        errorCategory: isHttp ? code : exception instanceof Error ? exception.name : 'UnknownError',
      });
    }

    const body: ErrorBody = {
      error: { code, message, ...(details ? { details } : {}) },
      requestId: request.requestId,
      path: request.originalUrl.split('?')[0] ?? request.originalUrl,
      timestamp: new Date().toISOString(),
    };
    response.status(status).json(body);
  }
}
