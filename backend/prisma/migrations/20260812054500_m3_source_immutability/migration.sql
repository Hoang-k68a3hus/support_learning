-- M3 hardening: enforce source-fact immutability at the PostgreSQL boundary.

CREATE FUNCTION "guard_verified_document_source_update"() RETURNS TRIGGER AS $$
BEGIN
    IF OLD."verified_at" IS NOT NULL THEN
        RAISE EXCEPTION 'verified document sources are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER "document_sources_verified_immutable_trigger"
BEFORE UPDATE ON "document_sources"
FOR EACH ROW EXECUTE FUNCTION "guard_verified_document_source_update"();

CREATE FUNCTION "guard_received_document_version_update"() RETURNS TRIGGER AS $$
BEGIN
    IF OLD."upload_state" = 'RECEIVED' THEN
        RAISE EXCEPTION 'received document versions are immutable' USING ERRCODE = '23514';
    END IF;

    IF NEW."upload_state" = 'RECEIVED' AND OLD."upload_state" <> 'RECEIVED' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM "document_sources" source
            WHERE source."document_version_id" = OLD."id"
              AND source."verified_at" IS NOT NULL
              AND source."etag" IS NOT NULL
              AND length(source."etag") > 0
        ) THEN
            RAISE EXCEPTION 'received document version requires verified final source metadata' USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER "document_versions_received_immutable_trigger"
BEFORE UPDATE ON "document_versions"
FOR EACH ROW EXECUTE FUNCTION "guard_received_document_version_update"();
