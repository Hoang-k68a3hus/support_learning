CREATE TYPE "OutboxStatus" AS ENUM ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED');

ALTER TABLE "outbox_events"
  ADD COLUMN "schema_version" INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN "status" "OutboxStatus" NOT NULL DEFAULT 'PENDING',
  ADD COLUMN "claim_owner" VARCHAR(160),
  ADD COLUMN "claim_expires_at" TIMESTAMPTZ(6),
  ADD COLUMN "last_error_code" VARCHAR(120),
  ADD COLUMN "last_error_at" TIMESTAMPTZ(6);

UPDATE "outbox_events"
SET "status" = 'PUBLISHED'::"OutboxStatus"
WHERE "published_at" IS NOT NULL;

ALTER TABLE "outbox_events"
  ADD CONSTRAINT "outbox_events_schema_version_check" CHECK ("schema_version" > 0),
  ADD CONSTRAINT "outbox_events_attempts_check" CHECK ("attempts" >= 0),
  ADD CONSTRAINT "outbox_events_state_shape_check" CHECK (
    (
      "status" = 'PENDING'::"OutboxStatus"
      AND "published_at" IS NULL
      AND "claim_owner" IS NULL
      AND "claim_expires_at" IS NULL
    )
    OR
    (
      "status" = 'PUBLISHING'::"OutboxStatus"
      AND "published_at" IS NULL
      AND "claim_owner" IS NOT NULL
      AND "claim_expires_at" IS NOT NULL
    )
    OR
    (
      "status" = 'PUBLISHED'::"OutboxStatus"
      AND "published_at" IS NOT NULL
      AND "claim_owner" IS NULL
      AND "claim_expires_at" IS NULL
    )
    OR
    (
      "status" = 'FAILED'::"OutboxStatus"
      AND "published_at" IS NULL
      AND "claim_owner" IS NULL
      AND "claim_expires_at" IS NULL
    )
  );

DROP INDEX IF EXISTS "outbox_events_pending_idx";

CREATE INDEX "outbox_events_pending_claim_idx"
  ON "outbox_events" ("available_at", "created_at")
  WHERE "status" = 'PENDING'::"OutboxStatus";

CREATE INDEX "outbox_events_publishing_lease_idx"
  ON "outbox_events" ("claim_expires_at", "created_at")
  WHERE "status" = 'PUBLISHING'::"OutboxStatus";
