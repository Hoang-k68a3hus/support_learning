import { calculateOutboxBackoffMs } from '../../src/async/outbox/outbox-backoff';

describe('calculateOutboxBackoffMs', () => {
  it('uses bounded exponential backoff', () => {
    expect(calculateOutboxBackoffMs(1, 100, 1000)).toBe(100);
    expect(calculateOutboxBackoffMs(2, 100, 1000)).toBe(200);
    expect(calculateOutboxBackoffMs(4, 100, 1000)).toBe(800);
    expect(calculateOutboxBackoffMs(5, 100, 1000)).toBe(1000);
    expect(calculateOutboxBackoffMs(20, 100, 1000)).toBe(1000);
  });

  it('rejects invalid inputs', () => {
    expect(() => calculateOutboxBackoffMs(0, 100, 1000)).toThrow('attempt');
    expect(() => calculateOutboxBackoffMs(1, 0, 1000)).toThrow('baseMs');
    expect(() => calculateOutboxBackoffMs(1, 1000, 100)).toThrow('maxMs');
  });
});
