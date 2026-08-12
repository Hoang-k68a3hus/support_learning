-- M3 Knowledge Library: authoritative metadata, immutable source versions and durable handoff state.

CREATE TYPE "DocumentStatus" AS ENUM ('ACTIVE', 'DELETED');
CREATE TYPE "DocumentUploadState" AS ENUM ('UPLOADING', 'RECEIVED', 'ABORTED');

CREATE TABLE "workspaces" (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "name" VARCHAR(120) NOT NULL,
    "normalized_name" VARCHAR(120) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "deleted_at" TIMESTAMPTZ(6),
    CONSTRAINT "workspaces_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "workspaces_name_nonempty_check" CHECK (length(btrim("name")) > 0),
    CONSTRAINT "workspaces_normalized_name_canonical_check" CHECK ("normalized_name" = lower(btrim("normalized_name")))
);

CREATE TABLE "folders" (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "parent_id" UUID,
    "name" VARCHAR(120) NOT NULL,
    "normalized_name" VARCHAR(120) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "deleted_at" TIMESTAMPTZ(6),
    CONSTRAINT "folders_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "folders_parent_not_self_check" CHECK ("parent_id" IS NULL OR "parent_id" <> "id"),
    CONSTRAINT "folders_name_nonempty_check" CHECK (length(btrim("name")) > 0),
    CONSTRAINT "folders_normalized_name_canonical_check" CHECK ("normalized_name" = lower(btrim("normalized_name")))
);

CREATE TABLE "tags" (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "name" VARCHAR(80) NOT NULL,
    "normalized_name" VARCHAR(80) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "tags_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "tags_name_nonempty_check" CHECK (length(btrim("name")) > 0),
    CONSTRAINT "tags_normalized_name_canonical_check" CHECK ("normalized_name" = lower(btrim("normalized_name")))
);

CREATE TABLE "documents" (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "folder_id" UUID,
    "title" VARCHAR(240) NOT NULL,
    "status" "DocumentStatus" NOT NULL DEFAULT 'ACTIVE',
    "current_version_id" UUID,
    "deleted_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "documents_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "documents_title_nonempty_check" CHECK (length(btrim("title")) > 0),
    CONSTRAINT "documents_status_deleted_at_check" CHECK (("status" = 'DELETED') = ("deleted_at" IS NOT NULL))
);

CREATE TABLE "document_versions" (
    "id" UUID NOT NULL,
    "document_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "upload_state" "DocumentUploadState" NOT NULL DEFAULT 'UPLOADING',
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "document_versions_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "document_versions_version_no_positive_check" CHECK ("version_no" > 0)
);

CREATE TABLE "document_sources" (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "staging_object_key" VARCHAR(512) NOT NULL,
    "object_key" VARCHAR(512) NOT NULL,
    "original_filename" VARCHAR(255) NOT NULL,
    "media_type" VARCHAR(160) NOT NULL,
    "size_bytes" BIGINT NOT NULL,
    "etag" VARCHAR(160),
    "checksum_sha256" CHAR(64),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "verified_at" TIMESTAMPTZ(6),
    CONSTRAINT "document_sources_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "document_sources_size_nonnegative_check" CHECK ("size_bytes" >= 0),
    CONSTRAINT "document_sources_verified_metadata_check" CHECK (
      "verified_at" IS NULL OR ("etag" IS NOT NULL AND length("etag") > 0)
    )
);

CREATE TABLE "workspace_sources" (
    "workspace_id" UUID NOT NULL,
    "document_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    CONSTRAINT "workspace_sources_pkey" PRIMARY KEY ("workspace_id", "document_id")
);

CREATE TABLE "document_tags" (
    "document_id" UUID NOT NULL,
    "tag_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    CONSTRAINT "document_tags_pkey" PRIMARY KEY ("document_id", "tag_id")
);

CREATE TABLE "outbox_events" (
    "id" UUID NOT NULL,
    "aggregate_type" VARCHAR(80) NOT NULL,
    "aggregate_id" UUID NOT NULL,
    "event_type" VARCHAR(120) NOT NULL,
    "payload" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "available_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "published_at" TIMESTAMPTZ(6),
    "attempts" INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT "outbox_events_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "outbox_events_attempts_nonnegative_check" CHECK ("attempts" >= 0)
);

CREATE TABLE "idempotency_records" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "scope" VARCHAR(160) NOT NULL,
    "key" VARCHAR(200) NOT NULL,
    "request_hash" VARCHAR(67) NOT NULL,
    "response_status" INTEGER NOT NULL,
    "response_body" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "idempotency_records_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "idempotency_records_hash_v1_check" CHECK ("request_hash" ~ '^v1:[0-9a-f]{64}$'),
    CONSTRAINT "idempotency_records_response_status_check" CHECK ("response_status" BETWEEN 200 AND 599)
);

CREATE TABLE "audit_logs" (
    "id" UUID NOT NULL,
    "actor_user_id" UUID,
    "action" VARCHAR(120) NOT NULL,
    "resource_type" VARCHAR(80) NOT NULL,
    "resource_id" UUID NOT NULL,
    "request_id" VARCHAR(128) NOT NULL,
    "metadata" JSONB NOT NULL,
    "occurred_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id")
);

ALTER TABLE "workspaces" ADD CONSTRAINT "workspaces_id_owner_id_key" UNIQUE ("id", "owner_id");
ALTER TABLE "folders" ADD CONSTRAINT "folders_id_owner_id_key" UNIQUE ("id", "owner_id");
ALTER TABLE "tags" ADD CONSTRAINT "tags_id_owner_id_key" UNIQUE ("id", "owner_id");
ALTER TABLE "documents" ADD CONSTRAINT "documents_id_owner_id_key" UNIQUE ("id", "owner_id");
ALTER TABLE "document_versions" ADD CONSTRAINT "document_versions_document_id_version_no_key" UNIQUE ("document_id", "version_no");
ALTER TABLE "document_versions" ADD CONSTRAINT "document_versions_id_document_id_key" UNIQUE ("id", "document_id");
ALTER TABLE "document_sources" ADD CONSTRAINT "document_sources_document_version_id_key" UNIQUE ("document_version_id");
ALTER TABLE "document_sources" ADD CONSTRAINT "document_sources_staging_object_key_key" UNIQUE ("staging_object_key");
ALTER TABLE "document_sources" ADD CONSTRAINT "document_sources_object_key_key" UNIQUE ("object_key");
ALTER TABLE "idempotency_records" ADD CONSTRAINT "idempotency_records_user_scope_key_key" UNIQUE ("user_id", "scope", "key");

CREATE UNIQUE INDEX "workspaces_owner_active_name_key" ON "workspaces"("owner_id", "normalized_name") WHERE "deleted_at" IS NULL;
CREATE UNIQUE INDEX "folders_owner_parent_active_name_key" ON "folders"("owner_id", "parent_id", "normalized_name") NULLS NOT DISTINCT WHERE "deleted_at" IS NULL;
CREATE UNIQUE INDEX "tags_owner_normalized_name_key" ON "tags"("owner_id", "normalized_name");
CREATE INDEX "workspaces_owner_updated_idx" ON "workspaces"("owner_id", "updated_at" DESC, "id" DESC);
CREATE INDEX "folders_owner_parent_idx" ON "folders"("owner_id", "parent_id");
CREATE INDEX "documents_owner_created_active_idx" ON "documents"("owner_id", "created_at" DESC, "id" DESC) WHERE "deleted_at" IS NULL;
CREATE INDEX "documents_folder_created_idx" ON "documents"("folder_id", "created_at" DESC, "id" DESC);
CREATE INDEX "document_versions_document_version_desc_idx" ON "document_versions"("document_id", "version_no" DESC);
CREATE INDEX "workspace_sources_document_workspace_idx" ON "workspace_sources"("document_id", "workspace_id");
CREATE INDEX "document_tags_tag_document_idx" ON "document_tags"("tag_id", "document_id");
CREATE INDEX "idempotency_records_expires_at_idx" ON "idempotency_records"("expires_at");
CREATE INDEX "outbox_events_pending_idx" ON "outbox_events"("available_at", "created_at") WHERE "published_at" IS NULL;
CREATE INDEX "audit_logs_actor_occurred_idx" ON "audit_logs"("actor_user_id", "occurred_at" DESC);
CREATE INDEX "audit_logs_resource_occurred_idx" ON "audit_logs"("resource_type", "resource_id", "occurred_at" DESC);

ALTER TABLE "workspaces" ADD CONSTRAINT "workspaces_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "folders" ADD CONSTRAINT "folders_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "folders" ADD CONSTRAINT "folders_parent_owner_fkey" FOREIGN KEY ("parent_id", "owner_id") REFERENCES "folders"("id", "owner_id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "tags" ADD CONSTRAINT "tags_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "documents" ADD CONSTRAINT "documents_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "documents" ADD CONSTRAINT "documents_folder_owner_fkey" FOREIGN KEY ("folder_id", "owner_id") REFERENCES "folders"("id", "owner_id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "document_versions" ADD CONSTRAINT "document_versions_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "documents"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "documents" ADD CONSTRAINT "documents_current_version_same_document_fkey" FOREIGN KEY ("current_version_id", "id") REFERENCES "document_versions"("id", "document_id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "document_sources" ADD CONSTRAINT "document_sources_document_version_id_fkey" FOREIGN KEY ("document_version_id") REFERENCES "document_versions"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "workspace_sources" ADD CONSTRAINT "workspace_sources_workspace_owner_fkey" FOREIGN KEY ("workspace_id", "owner_id") REFERENCES "workspaces"("id", "owner_id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "workspace_sources" ADD CONSTRAINT "workspace_sources_document_owner_fkey" FOREIGN KEY ("document_id", "owner_id") REFERENCES "documents"("id", "owner_id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "document_tags" ADD CONSTRAINT "document_tags_document_owner_fkey" FOREIGN KEY ("document_id", "owner_id") REFERENCES "documents"("id", "owner_id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "document_tags" ADD CONSTRAINT "document_tags_tag_owner_fkey" FOREIGN KEY ("tag_id", "owner_id") REFERENCES "tags"("id", "owner_id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "idempotency_records" ADD CONSTRAINT "idempotency_records_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "audit_logs" ADD CONSTRAINT "audit_logs_actor_user_id_fkey" FOREIGN KEY ("actor_user_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
