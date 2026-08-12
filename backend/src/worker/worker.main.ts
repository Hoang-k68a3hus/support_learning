import { NestFactory } from '@nestjs/core';
import { JsonLoggerService } from '../common/logging/json-logger.service';
import { WorkerModule } from './worker.module';
import { WorkerRuntimeService } from './worker-runtime.service';

async function main(): Promise<void> {
  const app = await NestFactory.createApplicationContext(WorkerModule, { bufferLogs: true });
  const logger = app.get(JsonLoggerService);
  app.useLogger(logger);
  const runtime = app.get(WorkerRuntimeService);

  let stopping = false;
  const requestStop = (signal: string): void => {
    if (stopping) return;
    stopping = true;
    logger.log('worker_shutdown_requested', { signal });
    void runtime.stop();
  };

  process.once('SIGTERM', () => requestStop('SIGTERM'));
  process.once('SIGINT', () => requestStop('SIGINT'));

  try {
    await runtime.start();
    await runtime.waitUntilStopped();
  } finally {
    await app.close();
  }
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'Unknown worker bootstrap failure';
  process.stderr.write(`${JSON.stringify({ level: 'error', message: 'worker_bootstrap_failed', detail: message })}\n`);
  process.exitCode = 1;
});
