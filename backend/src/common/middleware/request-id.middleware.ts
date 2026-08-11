import { Injectable, type NestMiddleware } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import type { NextFunction, Response } from 'express';
import type { RequestContext } from '../types/http-request';

const REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]{1,100}$/;

@Injectable()
export class RequestIdMiddleware implements NestMiddleware {
  use(request: RequestContext, response: Response, next: NextFunction): void {
    const incoming = request.header('x-request-id');
    request.requestId = incoming && REQUEST_ID_PATTERN.test(incoming) ? incoming : randomUUID();
    response.setHeader('x-request-id', request.requestId);
    next();
  }
}
