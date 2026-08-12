import { HttpException } from '@nestjs/common';

export class DomainHttpException extends HttpException {
  constructor(status: number, code: string, detail: string) {
    super({ statusCode: status, message: detail, code }, status);
  }
}
