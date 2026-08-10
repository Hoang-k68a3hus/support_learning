import { PasswordService } from '../../src/auth/password.service';

describe('PasswordService', () => {
  const service = new PasswordService();

  it('hashes with salt and verifies only the correct password', async () => {
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
});
