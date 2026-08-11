-- CreateEnum
CREATE TYPE "UserStatus" AS ENUM ('ACTIVE', 'SUSPENDED');

-- Add canonical identity and account status
ALTER TABLE "users"
ADD COLUMN "normalized_email" VARCHAR(320),
ADD COLUMN "status" "UserStatus" NOT NULL DEFAULT 'ACTIVE';

UPDATE "users"
SET "normalized_email" = lower(btrim("email"));

ALTER TABLE "users"
ALTER COLUMN "normalized_email" SET NOT NULL;

DROP INDEX "users_email_key";

ALTER TABLE "users"
DROP CONSTRAINT "users_email_canonical_check";

CREATE UNIQUE INDEX "users_normalized_email_key"
ON "users"("normalized_email");

ALTER TABLE "users"
ADD CONSTRAINT "users_normalized_email_canonical_check"
CHECK ("normalized_email" = lower(btrim("normalized_email")));

-- Add refresh-token rotation generation to the server-side session truth
ALTER TABLE "sessions"
ADD COLUMN "rotation_version" INTEGER NOT NULL DEFAULT 0;

ALTER TABLE "sessions"
ADD CONSTRAINT "sessions_rotation_version_nonnegative_check"
CHECK ("rotation_version" >= 0);
