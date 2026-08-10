import type { INestApplication } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Role } from '@prisma/client';
import { createHash, randomUUID } from 'node:crypto';
import request from 'supertest';
import { AppConfigService } from '../../src/config/app-config.service';
import { PrismaService } from '../../src/database/prisma.service';
import { createTestApp } from '../helpers/test-app';

type SupertestResponse = request.Response;
type SupertestTest = request.Test;

const student = {
  email: 'student@example.com',
  password: 'correct horse battery staple',
  fullName: 'Student One',
};

function refreshCookie(response: SupertestResponse): string {
  const setCookie = response.headers['set-cookie'];
  const values = Array.isArray(setCookie) ? setCookie : setCookie ? [setCookie] : [];
  const cookie = values.find((value) => value.startsWith('refresh_token='));
  if (!cookie) throw new Error('Expected refresh_token cookie');
  const separator = cookie.indexOf(';');
  return separator >= 0 ? cookie.slice(0, separator) : cookie;
}

function rawCookieValue(cookie: string): string {
  const separator = cookie.indexOf('=');
  if (separator < 0) throw new Error('Malformed cookie');
  return cookie.slice(separator + 1);
}

describe('Auth and RBAC E2E', () => {
  let app: INestApplication;
  let prisma: PrismaService;
  let config: AppConfigService;

  beforeAll(async () => {
    app = await createTestApp();
    prisma = app.get(PrismaService);
    config = app.get(AppConfigService);
  });

  beforeEach(async () => {
    await prisma.session.deleteMany();
    await prisma.user.deleteMany();
  });

  afterAll(async () => {
    await app.close();
  });

  function register(): SupertestTest {
    return request(app.getHttpServer()).post('/api/v1/auth/register').send(student);
  }

  function login(): SupertestTest {
    return request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: student.email, password: student.password });
  }

  it('registers a canonical STUDENT with a password hash and sanitized response', async () => {
    const response = await register().expect(201);
    expect(response.body.user).toMatchObject({
      email: student.email,
      fullName: student.fullName,
      role: Role.STUDENT,
    });
    expect(response.body.user).not.toHaveProperty('passwordHash');
    expect(response.body.user).not.toHaveProperty('password_hash');

    const stored = await prisma.user.findUniqueOrThrow({ where: { email: student.email } });
    expect(stored.passwordHash).not.toBe(student.password);
    expect(stored.passwordHash.startsWith('$argon2id$')).toBe(true);
    expect(stored.role).toBe(Role.STUDENT);
  });

  it('enforces unique canonical email at the database boundary', async () => {
    await register().expect(201);
    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, email: '  Student@Example.COM ' })
      .expect(409);

    await expect(
      prisma.user.create({
        data: {
          email: 'Upper@Example.com',
          passwordHash: '$argon2id$invalid-but-non-null',
          role: Role.STUDENT,
        },
      }),
    ).rejects.toBeDefined();
  });

  it('rejects malformed registration and public role escalation', async () => {
    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, password: 'short' })
      .expect(400);

    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, role: 'ADMIN' })
      .expect(400);

    expect(await prisma.user.count()).toBe(0);
  });

  it('rejects malformed login input at the DTO boundary', async () => {
    await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: 'not-an-email', password: '' })
      .expect(400);
  });

  it('logs in, creates a server-side session, and stores only the refresh-token hash', async () => {
    await register();
    const response = await login().expect(200);
    expect(response.body.accessToken).toEqual(expect.any(String));
    expect(response.body.user).not.toHaveProperty('passwordHash');

    const cookie = refreshCookie(response);
    const rawRefresh = rawCookieValue(cookie);
    const session = await prisma.session.findFirstOrThrow();
    expect(session.refreshTokenHash).not.toBe(rawRefresh);
    expect(session.refreshTokenHash).toBe(createHash('sha256').update(rawRefresh).digest('hex'));
  });

  it('uses a generic credential error for unknown users and wrong passwords', async () => {
    const unknown = await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: 'unknown@example.com', password: student.password })
      .expect(401);

    await register();
    const wrong = await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: student.email, password: 'definitely-the-wrong-password' })
      .expect(401);

    expect(unknown.body.error.message).toBe('Invalid email or password');
    expect(wrong.body.error.message).toBe('Invalid email or password');
  });

  it('accepts a valid access token and rejects missing, malformed, tampered, expired, or wrong-signature tokens', async () => {
    await register();
    const loginResponse = await login();
    const accessToken = loginResponse.body.accessToken as string;

    await request(app.getHttpServer())
      .get('/api/v1/users/me')
      .set('Authorization', `Bearer ${accessToken}`)
      .expect(200)
      .expect(({ body }: SupertestResponse) => {
        expect(body.email).toBe(student.email);
        expect(body.role).toBe(Role.STUDENT);
        expect(body).not.toHaveProperty('passwordHash');
      });

    await request(app.getHttpServer()).get('/api/v1/users/me').expect(401);
    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', 'Token abc').expect(401);

    const tampered = `${accessToken.slice(0, -1)}${accessToken.endsWith('a') ? 'b' : 'a'}`;
    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${tampered}`).expect(401);

    const decoded = new JwtService().decode(accessToken) as { sub: string; sid: string };
    const wrongSignature = await new JwtService().signAsync(
      { sub: decoded.sub, sid: decoded.sid, role: Role.STUDENT, type: 'access' },
      { secret: 'wrong-signature-secret-that-is-long-enough', expiresIn: 60 },
    );
    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${wrongSignature}`).expect(401);

    const expired = await new JwtService().signAsync(
      { sub: decoded.sub, sid: decoded.sid, role: Role.STUDENT, type: 'access' },
      { secret: config.jwtAccessSecret, expiresIn: -1 },
    );
    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${expired}`).expect(401);
  });

  it('rejects missing, malformed, expired, and server-expired refresh credentials', async () => {
    await register();
    const loginResponse = await login().expect(200);
    const accessToken = loginResponse.body.accessToken as string;
    const decoded = new JwtService().decode(accessToken) as { sub: string; sid: string };

    await request(app.getHttpServer()).post('/api/v1/auth/refresh').send({}).expect(401);
    await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', 'refresh_token=not-a-jwt')
      .send({})
      .expect(401);

    const expiredRefresh = await new JwtService().signAsync(
      { sub: decoded.sub, sid: decoded.sid, jti: randomUUID(), type: 'refresh' },
      { secret: config.jwtRefreshSecret, expiresIn: -1 },
    );
    await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', `refresh_token=${expiredRefresh}`)
      .send({})
      .expect(401);

    await prisma.session.update({
      where: { id: decoded.sid },
      data: { expiresAt: new Date(Date.now() - 1_000) },
    });
    await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', refreshCookie(loginResponse))
      .send({})
      .expect(401);
  });

  it('rotates refresh tokens: R1 succeeds once, R1 reuse fails, and R2 succeeds', async () => {
    await register();
    const loginResponse = await login();
    const r1 = refreshCookie(loginResponse);

    const firstRefresh = await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', r1)
      .send({})
      .expect(200);
    const r2 = refreshCookie(firstRefresh);
    expect(r2).not.toBe(r1);

    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}).expect(401);
    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r2).send({}).expect(200);
  });

  it('allows exactly one winner when two refresh requests race with the same token', async () => {
    await register();
    const r1 = refreshCookie(await login());

    const [a, b] = await Promise.all([
      request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}),
      request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}),
    ]);

    expect([a.status, b.status].sort()).toEqual([200, 401]);
    const winner = a.status === 200 ? a : b;
    const r2 = refreshCookie(winner);
    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r2).send({}).expect(200);
  });

  it('revokes the server-side session on logout so the old refresh token is rejected', async () => {
    await register();
    const loginResponse = await login();
    const accessToken = loginResponse.body.accessToken as string;
    const refresh = refreshCookie(loginResponse);

    await request(app.getHttpServer())
      .post('/api/v1/auth/logout')
      .set('Authorization', `Bearer ${accessToken}`)
      .set('Cookie', refresh)
      .send({})
      .expect(204);

    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', refresh).send({}).expect(401);
    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${accessToken}`).expect(401);

    const session = await prisma.session.findFirstOrThrow();
    expect(session.revokedAt).not.toBeNull();
  });

  it('completes the fresh-user auth lifecycle end to end', async () => {
    await register().expect(201);
    const loginResponse = await login().expect(200);
    const firstAccessToken = loginResponse.body.accessToken as string;
    const r1 = refreshCookie(loginResponse);

    await request(app.getHttpServer())
      .get('/api/v1/users/me')
      .set('Authorization', `Bearer ${firstAccessToken}`)
      .expect(200);

    const refreshResponse = await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', r1)
      .send({})
      .expect(200);
    const secondAccessToken = refreshResponse.body.accessToken as string;
    const r2 = refreshCookie(refreshResponse);

    await request(app.getHttpServer())
      .get('/api/v1/users/me')
      .set('Authorization', `Bearer ${secondAccessToken}`)
      .expect(200);

    await request(app.getHttpServer())
      .post('/api/v1/auth/logout')
      .set('Authorization', `Bearer ${secondAccessToken}`)
      .set('Cookie', r2)
      .send({})
      .expect(204);

    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r2).send({}).expect(401);
  });

  it('enforces the Session -> User foreign key', async () => {
    await expect(
      prisma.session.create({
        data: {
          id: randomUUID(),
          userId: randomUUID(),
          refreshTokenHash: 'a'.repeat(64),
          expiresAt: new Date(Date.now() + 60_000),
        },
      }),
    ).rejects.toBeDefined();
  });
});
