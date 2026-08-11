import type { INestApplication } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Role, UserStatus } from '@prisma/client';
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

  it('registers an ACTIVE STUDENT with normalized identity and a sanitized response', async () => {
    const response = await register().expect(201);
    expect(response.body.user).toMatchObject({
      email: student.email,
      fullName: null,
      role: Role.STUDENT,
      status: UserStatus.ACTIVE,
    });
    expect(response.body.user).not.toHaveProperty('passwordHash');
    expect(response.body.user).not.toHaveProperty('password_hash');
    expect(response.body.user).not.toHaveProperty('normalizedEmail');

    const stored = await prisma.user.findUniqueOrThrow({ where: { normalizedEmail: student.email } });
    expect(stored.email).toBe(student.email);
    expect(stored.normalizedEmail).toBe(student.email);
    expect(stored.passwordHash).not.toBe(student.password);
    expect(stored.passwordHash.startsWith('$argon2id$')).toBe(true);
    expect(stored.role).toBe(Role.STUDENT);
    expect(stored.status).toBe(UserStatus.ACTIVE);
  });

  it('enforces unique canonical normalized email at the database boundary', async () => {
    await register().expect(201);
    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, email: '  Student@Example.COM ' })
      .expect(409);

    await expect(
      prisma.user.create({
        data: {
          email: 'Upper@Example.com',
          normalizedEmail: 'Upper@Example.com',
          passwordHash: '$argon2id$invalid-but-non-null',
          role: Role.STUDENT,
        },
      }),
    ).rejects.toBeDefined();
  });

  it('allows only one concurrent registration for the same normalized email', async () => {
    const [first, second] = await Promise.all([
      request(app.getHttpServer()).post('/api/v1/auth/register').send(student),
      request(app.getHttpServer())
        .post('/api/v1/auth/register')
        .send({ ...student, email: 'Student@Example.COM' }),
    ]);

    expect([first.status, second.status].sort()).toEqual([201, 409]);
    expect(await prisma.user.count()).toBe(1);
  });

  it('rejects malformed registration, profile injection, and public role escalation', async () => {
    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, password: 'short' })
      .expect(400);

    await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, fullName: 'Should be profile-owned later' })
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

  it('uses RFC 9457 Problem Details for public REST errors', async () => {
    const response = await request(app.getHttpServer())
      .post('/api/v1/auth/register')
      .send({ ...student, password: 'short' })
      .expect(400);

    expect(response.headers['content-type']).toMatch(/^application\/problem\+json/);
    expect(response.body).toMatchObject({
      type: 'urn:support-learning:problem:validation-error',
      title: 'Bad Request',
      status: 400,
      detail: 'Request validation failed',
      instance: '/api/v1/auth/register',
      code: 'VALIDATION_ERROR',
      requestId: expect.any(String),
      errors: expect.any(Array),
    });
    expect(response.body).not.toHaveProperty('error');
    expect(response.headers['x-request-id']).toBe(response.body.requestId);
  });

  it('logs in, creates a versioned server-side session, and stores only the refresh-token hash', async () => {
    await register();
    const response = await login().expect(200);
    expect(response.body.accessToken).toEqual(expect.any(String));
    expect(response.body.user).toMatchObject({ status: UserStatus.ACTIVE });
    expect(response.body.user).not.toHaveProperty('passwordHash');

    const serializedCookie = Array.isArray(response.headers['set-cookie'])
      ? response.headers['set-cookie'].join(';')
      : String(response.headers['set-cookie']);
    expect(serializedCookie).toContain('HttpOnly');
    expect(serializedCookie).toContain('SameSite=Lax');
    expect(serializedCookie).toContain('Path=/api/v1/auth');

    const cookie = refreshCookie(response);
    const rawRefresh = rawCookieValue(cookie);
    const session = await prisma.session.findFirstOrThrow();
    expect(session.refreshTokenHash).not.toBe(rawRefresh);
    expect(session.refreshTokenHash).toBe(createHash('sha256').update(rawRefresh).digest('hex'));
    expect(session.rotationVersion).toBe(0);
  });

  it('uses a generic credential error for unknown users, wrong passwords, and suspended users', async () => {
    const unknown = await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: 'unknown@example.com', password: student.password })
      .expect(401);

    await register();
    const wrong = await request(app.getHttpServer())
      .post('/api/v1/auth/login')
      .send({ email: student.email, password: 'definitely-the-wrong-password' })
      .expect(401);

    await prisma.user.update({
      where: { normalizedEmail: student.email },
      data: { status: UserStatus.SUSPENDED },
    });
    const suspended = await login().expect(401);

    expect(unknown.body.detail).toBe('Invalid email or password');
    expect(wrong.body.detail).toBe('Invalid email or password');
    expect(suspended.body.detail).toBe('Invalid email or password');
    expect(unknown.body.code).toBe('AUTHENTICATION_ERROR');
    expect(wrong.body.code).toBe('AUTHENTICATION_ERROR');
    expect(suspended.body.code).toBe('AUTHENTICATION_ERROR');
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
        expect(body.status).toBe(UserStatus.ACTIVE);
        expect(body).not.toHaveProperty('passwordHash');
        expect(body).not.toHaveProperty('normalizedEmail');
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

  it('rotates refresh tokens with hash + rotationVersion CAS', async () => {
    await register();
    const loginResponse = await login();
    const r1 = refreshCookie(loginResponse);
    expect((await prisma.session.findFirstOrThrow()).rotationVersion).toBe(0);

    const firstRefresh = await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', r1)
      .send({})
      .expect(200);
    const r2 = refreshCookie(firstRefresh);
    expect(r2).not.toBe(r1);
    expect((await prisma.session.findFirstOrThrow()).rotationVersion).toBe(1);

    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}).expect(401);
    const secondRefresh = await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', r2)
      .send({})
      .expect(200);
    expect(refreshCookie(secondRefresh)).not.toBe(r2);
    expect((await prisma.session.findFirstOrThrow()).rotationVersion).toBe(2);
  });

  it('allows exactly one winner when two refresh requests race with the same token', async () => {
    await register();
    const r1 = refreshCookie(await login());

    const [a, b] = await Promise.all([
      request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}),
      request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}),
    ]);

    expect([a.status, b.status].sort()).toEqual([200, 401]);
    expect((await prisma.session.findFirstOrThrow()).rotationVersion).toBe(1);
    const winner = a.status === 200 ? a : b;
    const r2 = refreshCookie(winner);
    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r2).send({}).expect(200);
  });

  it('rejects access and refresh immediately when the persisted user becomes SUSPENDED', async () => {
    await register();
    const loginResponse = await login();
    const accessToken = loginResponse.body.accessToken as string;
    const refresh = refreshCookie(loginResponse);

    await prisma.user.update({
      where: { normalizedEmail: student.email },
      data: { status: UserStatus.SUSPENDED },
    });

    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${accessToken}`).expect(401);
    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', refresh).send({}).expect(401);
  });

  it('re-resolves the persisted role and rejects an access token with stale role context', async () => {
    await register();
    const loginResponse = await login();
    const oldAccessToken = loginResponse.body.accessToken as string;
    const refresh = refreshCookie(loginResponse);

    await prisma.user.update({
      where: { normalizedEmail: student.email },
      data: { role: Role.ADMIN },
    });

    await request(app.getHttpServer())
      .get('/api/v1/users/me')
      .set('Authorization', `Bearer ${oldAccessToken}`)
      .expect(401);

    const refreshResponse = await request(app.getHttpServer())
      .post('/api/v1/auth/refresh')
      .set('Cookie', refresh)
      .send({})
      .expect(200);
    const newAccessToken = refreshResponse.body.accessToken as string;
    const decoded = new JwtService().decode(newAccessToken) as { role: Role };
    expect(decoded.role).toBe(Role.ADMIN);

    await request(app.getHttpServer())
      .get('/api/v1/users/me')
      .set('Authorization', `Bearer ${newAccessToken}`)
      .expect(200)
      .expect(({ body }: SupertestResponse) => expect(body.role).toBe(Role.ADMIN));
  });

  it('leaves the session revoked when logout races with refresh', async () => {
    await register();
    const loginResponse = await login();
    const accessToken = loginResponse.body.accessToken as string;
    const r1 = refreshCookie(loginResponse);

    const [logoutResponse, refreshResponse] = await Promise.all([
      request(app.getHttpServer())
        .post('/api/v1/auth/logout')
        .set('Authorization', `Bearer ${accessToken}`)
        .set('Cookie', r1)
        .send({}),
      request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}),
    ]);

    expect(logoutResponse.status).toBe(204);
    expect([200, 401]).toContain(refreshResponse.status);

    await request(app.getHttpServer()).get('/api/v1/users/me').set('Authorization', `Bearer ${accessToken}`).expect(401);
    await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r1).send({}).expect(401);

    if (refreshResponse.status === 200) {
      const r2 = refreshCookie(refreshResponse);
      await request(app.getHttpServer()).post('/api/v1/auth/refresh').set('Cookie', r2).send({}).expect(401);
    }

    const session = await prisma.session.findFirstOrThrow();
    expect(session.revokedAt).not.toBeNull();
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

  it('enforces Session -> User foreign key and nonnegative rotationVersion', async () => {
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

    await register();
    const user = await prisma.user.findUniqueOrThrow({ where: { normalizedEmail: student.email } });
    await expect(
      prisma.session.create({
        data: {
          id: randomUUID(),
          userId: user.id,
          refreshTokenHash: 'b'.repeat(64),
          rotationVersion: -1,
          expiresAt: new Date(Date.now() + 60_000),
        },
      }),
    ).rejects.toBeDefined();
  });
});
