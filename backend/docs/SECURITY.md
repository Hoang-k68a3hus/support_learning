# Backend security notes

## Passwords

Passwords use Argon2id through the versioned `ARGON2_POLICY_V1` policy: memory cost 65536 KiB, time cost 3, parallelism 1, hash length 32. The same policy is used for the startup dummy hash that balances unknown-identity authentication work. Plaintext and password hashes are never serialized in API responses or intentionally logged. The public password boundary is 12–128 characters and does not silently truncate.

## Email identity

The HTTP boundary trims email input. The application stores the display `email` separately from `normalizedEmail`; the normalized key is `trim + lowercase` for this product. PostgreSQL enforces canonical normalized form and uniqueness on `normalized_email`, so case variants and concurrent registrations cannot bypass the identity invariant. `normalizedEmail` is internal and not exposed in the public user DTO.

## Account status

`User.status` is controlled vocabulary `ACTIVE | SUSPENDED`. Login requires ACTIVE. Refresh and every protected access check re-read the persisted User through the server-side Session and reject a SUSPENDED account immediately.

M2 does not expose an administrative status-mutation endpoint. When M10 introduces suspension, it must update the user, revoke all active sessions, and append the required audit record in the same PostgreSQL transaction. Unsuspension changes account state only and must not resurrect revoked sessions.

## Access tokens

Access JWTs contain `sub`, `sid`, `role`, `type`, `iat`, and `exp`, and use a signing secret distinct from refresh tokens. `JwtAuthGuard` verifies the JWT and then re-resolves the live Session, account status, and current persisted role. Logout, suspension, or role drift therefore takes effect before the JWT naturally expires.

## Refresh tokens and sessions

Refresh JWTs contain `sub`, `sid`, `jti`, `type`, `iat`, and `exp`. PostgreSQL stores only SHA-256 of the high-entropy signed refresh token; raw refresh tokens are never persisted.

Each Session has a nonnegative `rotationVersion`. Refresh compare-and-swap requires session ID, user ID, current refresh hash, expected rotation version, non-revoked state, and non-expired state, then atomically writes the next hash and increments the version. Two concurrent refreshes using the same token therefore have at most one successful rotation. Reuse of a successfully rotated token is rejected.

The graduation MVP does not keep a complete historical token-family ledger. It rejects non-current tokens but does not automatically revoke the entire family when an older token from multiple rotations ago is replayed. This is an explicit residual risk, not hidden unfinished behavior.

## Configuration secrets

Access and refresh signing secrets must be distinct and at least 32 characters. Startup validation also rejects known placeholder/example patterns such as `REPLACE_ME`, `CHANGE_ME`, and `PLACEHOLDER`, so copying `.env.example` unchanged cannot silently boot with a public repository secret. There are no fallback secrets.

## Cookies / CSRF

Refresh cookies use `HttpOnly`, `SameSite=Lax`, a narrow auth path, and `Secure` in production. CORS accepts only configured explicit origins with credentials enabled. This is designed for same-site deployment. If frontend/API deployment later requires `SameSite=None`, an explicit CSRF-token strategy must be added before changing the cookie policy.

## RBAC

Persistent roles are `STUDENT` and `ADMIN`. Public registration has no role/status fields and always creates `STUDENT + ACTIVE`. There is no public role-update path in M2. `@Roles(...)` + `RolesGuard` is the reusable coarse role policy; future resource modules must additionally enforce object ownership/ACLs at their query/service boundary. ADMIN does not implicitly bypass private learner-content ownership.

## Logging and RFC 9457 errors

Request logs contain request ID, method, route, status, latency, and user ID when available. Request bodies, headers, Authorization, cookies and tokens are not logged. Credential-shaped values are recursively redacted.

Public REST errors use RFC 9457 Problem Details (`application/problem+json`) with `type`, `title`, `status`, `detail`, `instance`, and required `code` + `requestId` extensions. Validation may add bounded `errors[]`. Internal failures never expose stack traces, SQL/storage internals, secrets, or raw dependency errors.

## Remaining M10 hardening

Per-route brute-force/rate limiting remains an operations milestone; login and refresh are the first route classes to protect. Password reset, MFA, trusted ADMIN provisioning, user-facing device/session management, and historical token-family compromise detection are outside M1/M2.
