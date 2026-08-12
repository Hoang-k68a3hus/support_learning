import { Module } from '@nestjs/common';
import { JobRetryPolicyService } from '../async/retry/job-retry-policy.service';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { ConfigModule } from '../config/config.module';
import { PrismaModule } from '../database/prisma.module';
import { DeadLetterService } from '../dead-letter/dead-letter.service';
import { InboxReceiptService } from '../inbox/inbox-receipt.service';
import { ConsumerDispatcherService } from './consumer-dispatcher.service';
import { ConsumerRegistryService } from './consumer-registry.service';
import { JobEnvelopeValidatorService } from './job-envelope-validator.service';
import { WORKER_JOB_HANDLERS } from './worker-job-handler';
import { WorkerRuntimeService } from './worker-runtime.service';

@Module({
  imports: [ConfigModule, PrismaModule],
  providers: [
    JsonLoggerService,
    InboxReceiptService,
    DeadLetterService,
    JobRetryPolicyService,
    JobEnvelopeValidatorService,
    { provide: WORKER_JOB_HANDLERS, useValue: [] },
    ConsumerRegistryService,
    ConsumerDispatcherService,
    WorkerRuntimeService,
  ],
  exports: [
    WORKER_JOB_HANDLERS,
    InboxReceiptService,
    DeadLetterService,
    JobRetryPolicyService,
    JobEnvelopeValidatorService,
    ConsumerRegistryService,
    ConsumerDispatcherService,
    WorkerRuntimeService,
  ],
})
export class WorkerModule {}
