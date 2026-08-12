import { Injectable } from '@nestjs/common';
import { Prisma, type AuditLog } from '@prisma/client';

export interface AuditWriteInput {
  actorUserId: string;
  action: string;
  resourceType: string;
  resourceId: string;
  requestId: string;
  metadata?: Record<string, unknown>;
}

@Injectable()
export class AuditService {
  append(tx: Prisma.TransactionClient, input: AuditWriteInput): Promise<AuditLog> {
    return tx.auditLog.create({
      data: {
        actorUserId: input.actorUserId,
        action: input.action,
        resourceType: input.resourceType,
        resourceId: input.resourceId,
        requestId: input.requestId,
        metadata: (input.metadata ?? {}) as Prisma.InputJsonValue,
      },
    });
  }
}
