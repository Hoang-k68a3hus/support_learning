export enum QueueName {
  PROCESSING = 'processing',
  LEARNING = 'learning',
  MAINTENANCE = 'maintenance',
}

export enum JobName {
  PROCESS_DOCUMENT_VERSION = 'PROCESS_DOCUMENT_VERSION',
}

export enum AsyncEventType {
  DOCUMENT_VERSION_RECEIVED = 'DOCUMENT_VERSION_RECEIVED',
}

export const JOB_CONTRACT_VERSION = 1 as const;
export const OUTBOX_EVENT_SCHEMA_VERSION = 1 as const;
export const JOB_RETRY_POLICY_KEY = 'PROCESSING_JOB_EXPONENTIAL_V1' as const;
export type JobRetryPolicyKey = typeof JOB_RETRY_POLICY_KEY;

export interface ProcessDocumentVersionPayload {
  documentId: string;
  documentVersionId: string;
  versionNo: number;
}

export type AsyncJobPayload = ProcessDocumentVersionPayload;

export interface JobEnvelope<TPayload extends AsyncJobPayload = AsyncJobPayload> {
  contractVersion: number;
  eventId: string;
  eventType: AsyncEventType;
  jobName: JobName;
  queueName: QueueName;
  aggregateType: string;
  aggregateId: string;
  occurredAt: string;
  correlationId: string;
  causationId?: string;
  traceparent?: string;
  requestId?: string;
  payload: TPayload;
}

export interface RoutedJob<TPayload extends AsyncJobPayload = AsyncJobPayload> {
  queueName: QueueName;
  jobName: JobName;
  retryPolicyKey: JobRetryPolicyKey;
  envelope: JobEnvelope<TPayload>;
}

export function canonicalJobId(jobName: JobName, contractVersion: number, eventId: string): string {
  return `${jobName}:v${contractVersion}:${eventId}`;
}

/**
 * BullMQ reserves ':' inside custom job IDs. Keep the architecture-level canonical
 * identity above, but encode the same fields with '~' at the transport boundary.
 */
export function bullMqTransportJobId(jobName: JobName, contractVersion: number, eventId: string): string {
  return `${jobName}~v${contractVersion}~${eventId}`;
}
