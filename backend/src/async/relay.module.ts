import { Module } from '@nestjs/common';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { ConfigModule } from '../config/config.module';
import { PrismaModule } from '../database/prisma.module';
import { EventRouterService } from './contracts/event-router.service';
import { OutboxRelayRepository } from './outbox/outbox-relay.repository';
import { OutboxRelayRunner } from './outbox/outbox-relay.runner';
import { JobRetryPolicyService } from './retry/job-retry-policy.service';
import { BullMqPublisherService } from './transport/bullmq-publisher.service';

@Module({
  imports: [ConfigModule, PrismaModule],
  providers: [
    JsonLoggerService,
    EventRouterService,
    JobRetryPolicyService,
    OutboxRelayRepository,
    BullMqPublisherService,
    OutboxRelayRunner,
  ],
  exports: [OutboxRelayRunner],
})
export class RelayModule {}
