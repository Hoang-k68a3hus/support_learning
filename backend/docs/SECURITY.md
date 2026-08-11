# Backend security notes

## Passwords

Passwords are hashed with Argon2id. Plaintext and password hashes are never serialized in API responses or intentionally logged. The public password policy is 12–128 characters; the backend does not silently truncate passwords.

## Email identity

Email is trimmed and lowercased at the HTTP/application boundary. PostgreSQL also enforces `email = lower(btrim(email))` plus a unique index, so concurrent registrations cannot bypass the invariant with a check-then-insert race.

## Access tokens

Access JWTs contain only `sub`, `sid`, `role`, `type`, `iat`, and `exp`. They use a signing secret distinct from refresh tokens. The authentication guard verifies the JWT and checks that the referenced server-side Session remains active, so logout revocation also invalidates existing access tokens on subsequent requests.

## Refresh tokens and sessions

Refresh JWTs contain `sub`, `sid`, `jti`, `type`, `iat`, and `exp`. PostgreSQL stores only SHA-256 of the high-entropy signed refresh token; raw refresh tokens are never persisted.

Rotation uses a database compare-and-swap update constrained by session ID, user ID, current refresh hash, non-revoked state and non-expired state. Two concurrent refresh requests using the same token can therefore have at most one successful rotation. Reuse of a successfully rotated token is rejected.

This milestone does **not** keep a complete historical token-family ledger, so it rejects old-token reuse but does not automatically revoke the whole family when replay is detected. That can be added later if the threat model requires it.

## Cookies / CSRF

Refresh cookies use `HttpOnly`, `SameSite=Lax`, a narrow auth path, and `Secure` in production. CORS accepts only configured explicit origins with credentials enabled. This is designed for same-site deployment. If the frontend/API are later deployed cross-site and `SameSite=None` becomes necessary, add an explicit CSRF token strategy before changing the cookie policy.

## RBAC

Controlled roles are `STUDENT` and `ADMIN`. Public registration has no role field and always creates `STUDENT`. There is no public role-update path in this milestone. `@Roles(...)` + `RolesGuard` is the reusable role policy mechanism; future resource modules must additionally enforce object ownership/ACLs in their service/query boundary.

## Logging and errors

Request logs contain request ID, method, route, status, latency, and user ID when available. Request bodies, headers, Authorization, cookies and tokens are not logged. The global exception filter returns generic internal errors and never exposes stack traces or SQL details to clients.

## Remaining hardening

Per-route brute-force/rate limiting is intentionally not claimed in this milestone because the repository has no existing Redis/rate-limit foundation. Login and refresh are the first candidates when that infrastructure is introduced. Password reset, MFA, device/session management and token-family replay revocation are also outside this milestone.
