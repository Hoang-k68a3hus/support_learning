CREATE TABLE "inbox_receipts" (
  "id" UUID NOT NULL,
  "consumer_name" VARCHAR(160) NOT NULL,
  "event_id" UUID NOT NULL,
  "job_name" VARCHAR(120) NOT NULL,
  "contract_version" INTEGER NOT NULL,
  "processed_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "result_hash" CHAR(64),
  "metadata" JSONB,

  CONSTRAINT "inbox_receipts_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "inbox_receipts_contract_version_positive_check" CHECK ("contract_version" > 0),
  CONSTRAINT "inbox_receipts_consumer_name_nonempty_check" CHECK (btrim("consumer_name") <> ''),
  CONSTRAINT "inbox_receipts_job_name_nonempty_check" CHECK (btrim("job_name") <> ''),
  CONSTRAINT "inbox_receipts_result_hash_check" CHECK (
    "result_hash" IS NULL OR "result_hash" ~ '^[0-9a-f]{64}$'
  )
);

CREATE UNIQUE INDEX "inbox_receipts_consumer_event_job_key"
  ON "inbox_receipts" ("consumer_name", "event_id", "job_name");

CREATE INDEX "inbox_receipts_event_id_idx"
  ON "inbox_receipts" ("event_id");

CREATE INDEX "inbox_receipts_processed_at_idx"
  ON "inbox_receipts" ("processed_at");

ALTER TABLE "inbox_receipts"
  ADD CONSTRAINT "inbox_receipts_event_id_fkey"
  FOREIGN KEY ("event_id") REFERENCES "outbox_events"("id")
  ON DELETE RESTRICT ON UPDATE CASCADE;
