import { HttpException, HttpStatus } from '@nestjs/common';

const MIN_HTTP_ERROR_STATUS = 400;
const MAX_HTTP_ERROR_STATUS = 599;

function validHttpStatus(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= MIN_HTTP_ERROR_STATUS && value <= MAX_HTTP_ERROR_STATUS;
}

export function resolveHttpErrorStatus(error: unknown): number {
  if (error instanceof HttpException) return error.getStatus();
  if (typeof error !== 'object' || error === null) return HttpStatus.INTERNAL_SERVER_ERROR;

  const candidate = error as { statusCode?: unknown; status?: unknown };
  if (validHttpStatus(candidate.statusCode)) return candidate.statusCode;
  if (validHttpStatus(candidate.status)) return candidate.status;
  return HttpStatus.INTERNAL_SERVER_ERROR;
}
