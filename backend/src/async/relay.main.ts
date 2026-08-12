import { NestFactory } from '@nestjs/core';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { OutboxRelayRunner } from './outbox/outbox-relay.runner';
import { RelayModule } from './relay.module';

async function main(): Promise<void> {
  const app = await NestFactory.createApplicationContext(RelayModule, { bufferLogs: true });
  const logger = app.get(JsonLoggerService);
  app.useLogger(logger);
  const runner = app.get(OutboxRelayRunner);

  let stopping = false;
  const requestStop = (signal: string): void => {
    if (stopping) return;
    stopping = true;
    logger.log('outbox_relay_shutdown_requested', { signal });
    runner.stop();
  };

  process.once('SIGTERM', () => requestStop('SIGTERM'));
  process.once('SIGINT', () => requestStop('SIGINT'));

  try {
    await runner.run();
  } finally {
    await app.close();
  }
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'Unknown relay bootstrap failure';
  process.stderr.write(`${JSON.stringify({ level: 'error', message: 'outbox_relay_bootstrap_failed', detail: message })}\n`);
  process.exitCode = 1;
});
