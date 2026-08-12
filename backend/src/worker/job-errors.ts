export abstract class WorkerJobError extends Error {
  protected constructor(
    readonly code: string,
    readonly redactedMessage: string,
  ) {
    super(redactedMessage);
    this.name = new.target.name;
  }
}

export class RetryableJobError extends WorkerJobError {
  constructor(code: string, redactedMessage: string) {
    super(code, redactedMessage);
  }
}

export class TerminalJobError extends WorkerJobError {
  constructor(code: string, redactedMessage: string) {
    super(code, redactedMessage);
  }
}

export class StaleJobError extends WorkerJobError {
  constructor(code: string, redactedMessage: string) {
    super(code, redactedMessage);
  }
}
