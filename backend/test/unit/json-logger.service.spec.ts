import { JsonLoggerService } from '../../src/common/logging/json-logger.service';

describe('JsonLoggerService', () => {
  it('redacts credential-shaped values recursively', () => {
    const write = jest.spyOn(process.stdout, 'write').mockImplementation(() => true);
    try {
      new JsonLoggerService().log('request', {
        password: 'plain-password',
        authorization: 'Bearer signed.jwt.token',
        nested: {
          refreshToken: 'raw-refresh-token',
          databaseUrl: 'postgresql://user:password@localhost:5432/app',
        },
      });

      const output = write.mock.calls.map(([chunk]) => String(chunk)).join('');
      expect(output).not.toContain('plain-password');
      expect(output).not.toContain('signed.jwt.token');
      expect(output).not.toContain('raw-refresh-token');
      expect(output).not.toContain('user:password');
      expect(output).toContain('[REDACTED]');
    } finally {
      write.mockRestore();
    }
  });
});
