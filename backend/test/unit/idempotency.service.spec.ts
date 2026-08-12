import type { AppConfigService } from '../../src/config/app-config.service';
import { IdempotencyService } from '../../src/idempotency/idempotency.service';

describe('IdempotencyService CanonicalHashV1', () => {
  const service = new IdempotencyService({ idempotencyTtlSeconds: 86400 } as AppConfigService);

  it('is independent of object property order', () => {
    const a = service.canonicalHashV1({ title: 'A', folderId: null, nested: { b: 2, a: 1 } });
    const b = service.canonicalHashV1({ nested: { a: 1, b: 2 }, folderId: null, title: 'A' });
    expect(a).toBe(b);
    expect(a).toMatch(/^v1:[0-9a-f]{64}$/);
  });

  it('preserves semantic array order', () => {
    expect(service.canonicalHashV1({ values: ['a', 'b'] })).not.toBe(service.canonicalHashV1({ values: ['b', 'a'] }));
  });
});
