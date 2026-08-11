# Authentication API

Base path: `/api/v1`.

## POST `/auth/register`

Public. Unknown fields are rejected.

Request:

```json
{ "email": "student@example.com", "password": "at-least-12-characters", "fullName": "Student" }
```

`role` is deliberately not accepted. Success `201`:

```json
{ "user": { "id": "uuid", "email": "student@example.com", "fullName": "Student", "role": "STUDENT", "createdAt": "...", "updatedAt": "..." } }
```

Common errors: `400` validation, `409` duplicate canonical email.

## POST `/auth/login`

Public. Request contains `email` and `password`. Success `200` returns sanitized `user` + short-lived `accessToken` and sets a rotated-capable refresh token in the `refresh_token` cookie.

Invalid email and wrong password both return the same `401` message to reduce account enumeration.

## POST `/auth/refresh`

Public in the access-token sense; requires the HttpOnly `refresh_token` cookie. Success `200` returns a new access token and replaces the refresh cookie. Refresh rotation is one-time: once `R1` successfully becomes `R2`, `R1` is rejected.

## POST `/auth/logout`

Requires `Authorization: Bearer <access-token>`. Success `204`. The server revokes the associated Session row and clears the refresh cookie. Subsequent refresh and access checks for that session fail.

## GET `/users/me`

Requires a valid access token and an active server-side Session. Returns the current sanitized user from the validated principal, never from a client-supplied user ID.

## Token transport

Access tokens are returned in JSON and sent as Bearer tokens. Refresh tokens are not returned in JSON; they are stored in an HttpOnly cookie with `SameSite=Lax`, `Secure` in production, and path `/api/v1/auth`.
