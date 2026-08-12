import { Injectable } from '@nestjs/common';
import { AsyncContractError } from '../async/contracts/async-contract.error';
import {
  AsyncEventType,
  JOB_CONTRACT_VERSION,
  type JobEnvelope,
  JobName,
  type ProcessDocumentVersionPayload,
  QueueName,
} from '../async/contracts/async-contracts';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TOP_LEVEL_KEYS = new Set([
  'contractVersion',
  'eventId',
  'eventType',
  'jobName',
  'queueName',
  'aggregateType',
  'aggregateId',
  'occurredAt',
  'correlationId',
  'causationId',
  'traceparent',
  'requestId',
  'payload',
]);
const PROCESS_DOCUMENT_KEYS = new Set(['documentId', 'documentVersionId', 'versionNo']);

export interface DeliveryIdentity {
  queueName: QueueName;
  bullMqJobName: string;
  bullMqJobId?: string;
  attempt: number;
  maxAttempts: number;
}

@Injectable()
export class JobEnvelopeValidatorService {
  parse(raw: unknown, delivery: DeliveryIdentity): JobEnvelope<ProcessDocumentVersionPayload> {
    const envelope = this.requireObject(raw, 'Job envelope');
    this.rejectUnknownKeys(envelope, TOP_LEVEL_KEYS, 'Job envelope');

    const contractVersion = this.requirePositiveInteger(envelope, 'contractVersion');
    if (contractVersion !== JOB_CONTRACT_VERSION) {
      throw new AsyncContractError(
        'WORKER_CONTRACT_VERSION_UNSUPPORTED',
        `Unsupported worker contract version: ${contractVersion}`,
      );
    }

    const eventId = this.requireUuid(envelope, 'eventId');
    const eventType = this.requireLiteral(envelope, 'eventType', AsyncEventType.DOCUMENT_VERSION_RECEIVED);
    const jobName = this.requireLiteral(envelope, 'jobName', JobName.PROCESS_DOCUMENT_VERSION);
    const queueName = this.requireLiteral(envelope, 'queueName', QueueName.PROCESSING);
    if (delivery.queueName !== queueName || delivery.bullMqJobName !== String(jobName)) {
      throw new AsyncContractError(
        'WORKER_DELIVERY_IDENTITY_MISMATCH',
        `BullMQ delivery identity does not match envelope: ${delivery.queueName}/${delivery.bullMqJobName}`,
      );
    }

    const aggregateType = this.requireLiteral(envelope, 'aggregateType', 'DocumentVersion');
    const aggregateId = this.requireUuid(envelope, 'aggregateId');
    const occurredAt = this.requireIsoDate(envelope, 'occurredAt');
    const correlationId = this.requireUuid(envelope, 'correlationId');
    const payload = this.requireObject(envelope.payload, 'Job payload');
    this.rejectUnknownKeys(payload, PROCESS_DOCUMENT_KEYS, 'PROCESS_DOCUMENT_VERSION payload');

    const documentId = this.requireUuid(payload, 'documentId');
    const documentVersionId = this.requireUuid(payload, 'documentVersionId');
    const versionNo = this.requirePositiveInteger(payload, 'versionNo');
    if (aggregateId !== documentVersionId) {
      throw new AsyncContractError(
        'WORKER_AGGREGATE_MISMATCH',
        'PROCESS_DOCUMENT_VERSION aggregateId must equal documentVersionId',
      );
    }

    return {
      contractVersion,
      eventId,
      eventType,
      jobName,
      queueName,
      aggregateType,
      aggregateId,
      occurredAt,
      correlationId,
      causationId: this.optionalString(envelope, 'causationId'),
      traceparent: this.optionalString(envelope, 'traceparent'),
      requestId: this.optionalString(envelope, 'requestId'),
      payload: { documentId, documentVersionId, versionNo },
    };
  }

  private requireObject(value: unknown, label: string): Record<string, unknown> {
    if (value === null || Array.isArray(value) || typeof value !== 'object') {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${label} must be an object`);
    }
    return value as Record<string, unknown>;
  }

  private rejectUnknownKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>, label: string): void {
    const unknown = Object.keys(value).filter((key) => !allowed.has(key));
    if (unknown.length > 0) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${label} contains unknown fields: ${unknown.join(', ')}`);
    }
  }

  private requireUuid(value: Record<string, unknown>, key: string): string {
    const field = value[key];
    if (typeof field !== 'string' || !UUID_PATTERN.test(field)) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${key} must be a UUID`);
    }
    return field;
  }

  private requirePositiveInteger(value: Record<string, unknown>, key: string): number {
    const field = value[key];
    if (typeof field !== 'number' || !Number.isSafeInteger(field) || field <= 0) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${key} must be a positive safe integer`);
    }
    return field;
  }

  private requireLiteral<T extends string>(value: Record<string, unknown>, key: string, expected: T): T {
    if (value[key] !== expected) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${key} must be ${expected}`);
    }
    return expected;
  }

  private requireIsoDate(value: Record<string, unknown>, key: string): string {
    const field = value[key];
    if (typeof field !== 'string' || Number.isNaN(Date.parse(field))) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${key} must be an ISO-8601 timestamp`);
    }
    return field;
  }

  private optionalString(value: Record<string, unknown>, key: string): string | undefined {
    const field = value[key];
    if (field === undefined) return undefined;
    if (typeof field !== 'string' || field.length === 0 || field.length > 512) {
      throw new AsyncContractError('WORKER_ENVELOPE_INVALID', `${key} must be a non-empty string when provided`);
    }
    return field;
  }
}
