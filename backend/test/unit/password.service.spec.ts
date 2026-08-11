import { PasswordService } from '../../src/auth/password.service';

describe('PasswordService', () => {
  it('hashes with salt and verifies only the correct password', async () => {
    const service = new PasswordService();
    const password = 'correct horse battery staple';
    const first = await service.hash(password);
    const second = await service.hash(password);

    expect(first).not.toBe(password);
    expect(second).not.toBe(password);
    expect(first).not.toBe(second);
    await expect(service.verify(first, password)).resolves.toBe(true);
    await expect(service.verify(first, 'wrong password')).resolves.toBe(false);
    await expect(service.verify(second, password)).resolves.toBe(true);
  });

  it('runs a dummy verification for an unknown authentication identity', async () => {
    const service = new PasswordService();
    await service.onModuleInit();

    await expect(service.verifyForAuthentication(null, 'attempted password')).resolves.toBe(false);

    const realHash = await service.hash('known password');
    await expect(service.verifyForAuthentication(realHash, 'known password')).resolves.toBe(true);
    await expect(service.verifyForAuthentication(realHash, 'wrong password')).resolves.toBe(false);
  });
});
