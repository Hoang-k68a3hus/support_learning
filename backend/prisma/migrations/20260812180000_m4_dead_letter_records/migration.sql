CREATE TABLE "dead_letter_records" (
  "id" UUID NOT NULL,
  "event_id" UUID NOT NULL,
  "job_name" VARCHAR(120) NOT NULL,
  "queue_name" VARCHAR(80) NOT NULL,
  "contract_version" INTEGER NOT NULL,
  "error_code" VARCHAR(120) NOT NULL,
  "error_message_redacted" VARCHAR(500) NOT NULL,
  "stack_fingerprint" CHAR(64),
  "payload_hash" CHAR(64),
  "attempts" INTEGER NOT NULL,
  "failed_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "replay_count" INTEGER NOT NULL DEFAULT 0,
  "last_replay_at" TIMESTAMPTZ(6),
  "resolved_at" TIMESTAMPTZ(6),

  CONSTRAINT "dead_letter_records_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "dead_letter_records_job_name_nonempty_check" CHECK (btrim("job_name") <> ''),
  CONSTRAINT "dead_letter_records_queue_name_nonempty_check" CHECK (btrim("queue_name") <> ''),
  CONSTRAINT "dead_letter_records_contract_version_positive_check" CHECK ("contract_version" > 0),
  CONSTRAINT "dead_letter_records_error_code_nonempty_check" CHECK (btrim("error_code") <> ''),
  CONSTRAINT "dead_letter_records_error_message_nonempty_check" CHECK (btrim("error_message_redacted") <> ''),
  CONSTRAINT "dead_letter_records_attempts_positive_check" CHECK ("attempts" > 0),
  CONSTRAINT "dead_letter_records_replay_count_nonnegative_check" CHECK ("replay_count" >= 0),
  CONSTRAINT "dead_letter_records_stack_fingerprint_check" CHECK (
    "stack_fingerprint" IS NULL OR "stack_fingerprint" ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT "dead_letter_records_payload_hash_check" CHECK (
    "payload_hash" IS NULL OR "payload_hash" ~ '^[0-9a-f]{64}$'
  ),
  CONSTRAINT "dead_letter_records_replay_shape_check" CHECK (
    ("replay_count" = 0 AND "last_replay_at" IS NULL)
    OR ("replay_count" > 0 AND "last_replay_at" IS NOT NULL)
  )
);

CREATE INDEX "dead_letter_records_event_id_idx"
  ON "dead_letter_records" ("event_id");

CREATE INDEX "dead_letter_records_resolution_failed_at_idx"
  ON "dead_letter_records" ("resolved_at", "failed_at" DESC);

CREATE UNIQUE INDEX "dead_letter_records_event_job_active_key"
  ON "dead_letter_records" ("event_id", "job_name")
  WHERE "resolved_at" IS NULL;

ALTER TABLE "dead_letter_records"
  ADD CONSTRAINT "dead_letter_records_event_id_fkey"
  FOREIGN KEY ("event_id") REFERENCES "outbox_events"("id")
  ON DELETE RESTRICT ON UPDATE CASCADE;
