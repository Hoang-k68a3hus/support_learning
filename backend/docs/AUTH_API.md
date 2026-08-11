# Authentication API

Base path: `/api/v1`.

## POST `/auth/register`

Public. Unknown fields are rejected.

Request:

```json
{ "email": "student@example.com", "password": "at-least-12-characters" }
```

`role`, `status`, `fullName`, and internal identity fields are deliberately not accepted. Success `201` returns the sanitized user. New accounts are always `STUDENT + ACTIVE`.

The server preserves the trimmed display email but derives a separate `normalizedEmail = trim + lowercase` lookup key. `normalizedEmail` is unique in PostgreSQL and is never returned in public DTOs.

Common errors: `400` validation, `409` duplicate normalized email.

## POST `/auth/login`

Public. Request contains `email` and `password`. Success `200` returns sanitized `user` + short-lived `accessToken` and sets a refresh token in the `refresh_token` cookie.

Unknown email, wrong password, and a suspended account all return the same `401` credential message. The password-verification path performs a dummy Argon2id verification for unknown identities to reduce timing enumeration.

## POST `/auth/refresh`

Public in the access-token sense; requires the HttpOnly `refresh_token` cookie. Success `200` returns a new access token and replaces the refresh cookie.

Rotation is one-time and server-side. The Session CAS requires the current refresh-token hash, current `rotationVersion`, active/non-expired Session, and matching user. A successful rotation increments `rotationVersion`; concurrent refresh with the same token has exactly one winner. Suspended users cannot refresh.

## POST `/auth/logout`

Requires `Authorization: Bearer <access-token>`. Success `204`. The server revokes the associated Session row and clears the refresh cookie. Subsequent refresh and protected access checks for that Session fail.

## GET `/users/me`

Requires a valid access token plus an active server-side Session and `User.status=ACTIVE`. Authorization re-resolves the current persisted role; stale role claims are rejected rather than trusted. The endpoint resolves identity from the validated principal, never from a client-supplied user ID.

## Problem Details

All REST errors use `Content-Type: application/problem+json` and the RFC 9457 shape:

```json
{
  "type": "urn:support-learning:problem:validation-error",
  "title": "Bad Request",
  "status": 400,
  "detail": "Request validation failed",
  "instance": "/api/v1/auth/register",
  "code": "VALIDATION_ERROR",
  "requestId": "uuid-or-valid-client-request-id",
  "errors": ["password must be longer than or equal to 12 characters"]
}
```

`code` and `requestId` are required application extensions. `errors` is present only when bounded validation details are useful. Internal exceptions never expose stack traces, SQL, secrets, or provider internals.

## Token transport

Access tokens are returned in JSON and sent as Bearer tokens. Refresh tokens are not returned in JSON; they are stored in an HttpOnly cookie with `SameSite=Lax`, `Secure` in production, and path `/api/v1/auth`.
