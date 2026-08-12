import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { AsyncContractError } from './async-contract.error';
import {
  AsyncEventType,
  JOB_CONTRACT_VERSION,
  JobName,
  OUTBOX_EVENT_SCHEMA_VERSION,
  OUTBOX_RETRY_POLICY_KEY,
  type ProcessDocumentVersionPayload,
  QueueName,
  type RoutedJob,
} from './async-contracts';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface RoutableOutboxEvent {
  id: string;
  aggregateType: string;
  aggregateId: string;
  eventType: string;
  schemaVersion: number;
  payload: Prisma.JsonValue;
  createdAt: Date;
}

@Injectable()
export class EventRouterService {
  route(event: RoutableOutboxEvent): RoutedJob[] {
    if (event.eventType !== AsyncEventType.DOCUMENT_VERSION_RECEIVED) {
      throw new AsyncContractError('ASYNC_EVENT_TYPE_UNSUPPORTED', `Unsupported event type: ${event.eventType}`);
    }
    if (event.schemaVersion !== OUTBOX_EVENT_SCHEMA_VERSION) {
      throw new AsyncContractError(
        'ASYNC_EVENT_SCHEMA_UNSUPPORTED',
        `Unsupported ${event.eventType} schema version: ${event.schemaVersion}`,
      );
    }

    const payload = this.requireObject(event.payload);
    const jobPayload: ProcessDocumentVersionPayload = {
      documentId: this.requireUuid(payload, 'documentId'),
      documentVersionId: this.requireUuid(payload, 'documentVersionId'),
      versionNo: this.requirePositiveInteger(payload, 'versionNo'),
    };
    if (event.aggregateType !== 'DocumentVersion' || event.aggregateId !== jobPayload.documentVersionId) {
      throw new AsyncContractError(
        'ASYNC_EVENT_AGGREGATE_MISMATCH',
        'DOCUMENT_VERSION_RECEIVED aggregate must match documentVersionId',
      );
    }

    return [
      {
        queueName: QueueName.PROCESSING,
        jobName: JobName.PROCESS_DOCUMENT_VERSION,
        retryPolicyKey: OUTBOX_RETRY_POLICY_KEY,
        envelope: {
          contractVersion: JOB_CONTRACT_VERSION,
          eventId: event.id,
          eventType: AsyncEventType.DOCUMENT_VERSION_RECEIVED,
          jobName: JobName.PROCESS_DOCUMENT_VERSION,
          queueName: QueueName.PROCESSING,
          aggregateType: event.aggregateType,
          aggregateId: event.aggregateId,
          occurredAt: event.createdAt.toISOString(),
          correlationId: event.id,
          payload: jobPayload,
        },
      },
    ];
  }

  private requireObject(value: Prisma.JsonValue): Record<string, Prisma.JsonValue> {
    if (value === null || Array.isArray(value) || typeof value !== 'object') {
      throw new AsyncContractError('ASYNC_EVENT_PAYLOAD_INVALID', 'Event payload must be a JSON object');
    }
    return value as Record<string, Prisma.JsonValue>;
  }

  private requireUuid(payload: Record<string, Prisma.JsonValue>, key: string): string {
    const value = payload[key];
    if (typeof value !== 'string' || !UUID_PATTERN.test(value)) {
      throw new AsyncContractError('ASYNC_EVENT_PAYLOAD_INVALID', `${key} must be a UUID`);
    }
    return value;
  }

  private requirePositiveInteger(payload: Record<string, Prisma.JsonValue>, key: string): number {
    const value = payload[key];
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
      throw new AsyncContractError('ASYNC_EVENT_PAYLOAD_INVALID', `${key} must be a positive safe integer`);
    }
    return value;
  }
}
