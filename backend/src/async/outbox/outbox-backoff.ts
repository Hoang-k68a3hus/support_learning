export function calculateOutboxBackoffMs(attempt: number, baseMs: number, maxMs: number): number {
  if (!Number.isSafeInteger(attempt) || attempt <= 0) throw new Error('attempt must be a positive safe integer');
  if (!Number.isSafeInteger(baseMs) || baseMs <= 0) throw new Error('baseMs must be a positive safe integer');
  if (!Number.isSafeInteger(maxMs) || maxMs < baseMs) throw new Error('maxMs must be a safe integer >= baseMs');

  let delay = baseMs;
  for (let currentAttempt = 1; currentAttempt < attempt && delay < maxMs; currentAttempt += 1) {
    delay = Math.min(maxMs, delay * 2);
  }
  return delay;
}
