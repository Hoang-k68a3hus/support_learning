import { ArgumentsHost, Catch, HttpException, HttpStatus, type ExceptionFilter } from '@nestjs/common';
import type { Response } from 'express';
import { JsonLoggerService } from '../logging/json-logger.service';
import type { RequestContext } from '../types/http-request';
import { resolveHttpErrorStatus } from './http-error';

interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  code: string;
  requestId: string;
  errors?: string[];
}

const INTERNAL_SERVER_ERROR_STATUS = Number(HttpStatus.INTERNAL_SERVER_ERROR);

const STATUS_CODES: Partial<Record<number, string>> = {
  [HttpStatus.BAD_REQUEST]: 'VALIDATION_ERROR',
  [HttpStatus.UNAUTHORIZED]: 'AUTHENTICATION_ERROR',
  [HttpStatus.FORBIDDEN]: 'AUTHORIZATION_ERROR',
  [HttpStatus.NOT_FOUND]: 'NOT_FOUND',
  [HttpStatus.CONFLICT]: 'CONFLICT',
  [HttpStatus.PRECONDITION_FAILED]: 'PRECONDITION_FAILED',
  [HttpStatus.PAYLOAD_TOO_LARGE]: 'PAYLOAD_TOO_LARGE',
  [HttpStatus.UNPROCESSABLE_ENTITY]: 'BUSINESS_INVARIANT_VIOLATION',
  [HttpStatus.TOO_MANY_REQUESTS]: 'RATE_LIMITED',
  [HttpStatus.SERVICE_UNAVAILABLE]: 'DEPENDENCY_UNAVAILABLE',
};

const STATUS_TITLES: Partial<Record<number, string>> = {
  [HttpStatus.BAD_REQUEST]: 'Bad Request',
  [HttpStatus.UNAUTHORIZED]: 'Unauthorized',
  [HttpStatus.FORBIDDEN]: 'Forbidden',
  [HttpStatus.NOT_FOUND]: 'Not Found',
  [HttpStatus.CONFLICT]: 'Conflict',
  [HttpStatus.PRECONDITION_FAILED]: 'Precondition Failed',
  [HttpStatus.PAYLOAD_TOO_LARGE]: 'Payload Too Large',
  [HttpStatus.UNPROCESSABLE_ENTITY]: 'Unprocessable Entity',
  [HttpStatus.TOO_MANY_REQUESTS]: 'Too Many Requests',
  [HttpStatus.SERVICE_UNAVAILABLE]: 'Service Unavailable',
  [HttpStatus.INTERNAL_SERVER_ERROR]: 'Internal Server Error',
};

function problemType(code: string): string {
  return `urn:support-learning:problem:${code.toLowerCase().replaceAll('_', '-')}`;
}

function extractHttpDetail(exception: HttpException): { detail: string; errors?: string[] } {
  const exceptionResponse = exception.getResponse();
  if (typeof exceptionResponse === 'string') return { detail: exceptionResponse };
  if (typeof exceptionResponse !== 'object' || exceptionResponse === null) return { detail: 'Request failed' };

  const value = exceptionResponse as { message?: string | string[] };
  if (Array.isArray(value.message)) {
    return { detail: 'Request validation failed', errors: value.message };
  }
  if (typeof value.message === 'string') return { detail: value.message };
  return { detail: 'Request failed' };
}

@Catch()
export class HttpExceptionFilter implements ExceptionFilter {
  constructor(private readonly logger: JsonLoggerService) {}

  catch(exception: unknown, host: ArgumentsHost): void {
    const http = host.switchToHttp();
    const request = http.getRequest<RequestContext>();
    const response = http.getResponse<Response>();
    const status = resolveHttpErrorStatus(exception);
    const code = STATUS_CODES[status] ?? (status >= INTERNAL_SERVER_ERROR_STATUS ? 'INTERNAL_ERROR' : 'HTTP_ERROR');
    const title = STATUS_TITLES[status] ?? (status >= INTERNAL_SERVER_ERROR_STATUS ? 'Internal Server Error' : 'Request Failed');

    let detail = status >= INTERNAL_SERVER_ERROR_STATUS ? 'Internal server error' : title;
    let errors: string[] | undefined;
    if (status < INTERNAL_SERVER_ERROR_STATUS && exception instanceof HttpException) {
      const extracted = extractHttpDetail(exception);
      detail = extracted.detail;
      errors = extracted.errors;
    } else if (status === HttpStatus.PAYLOAD_TOO_LARGE) {
      detail = 'Request payload is too large';
    }

    if (status >= INTERNAL_SERVER_ERROR_STATUS) {
      this.logger.error('http_exception', {
        requestId: request.requestId,
        method: request.method,
        route: request.originalUrl.split('?')[0],
        errorCategory: exception instanceof Error ? exception.name : 'UnknownError',
      });
    }

    const instance = request.originalUrl.split('?')[0] ?? request.originalUrl;
    const body: ProblemDetails = {
      type: problemType(code),
      title,
      status,
      detail,
      instance,
      code,
      requestId: request.requestId,
      ...(errors ? { errors } : {}),
    };

    response.setHeader('Content-Type', 'application/problem+json');
    response.status(status).json(body);
  }
}
