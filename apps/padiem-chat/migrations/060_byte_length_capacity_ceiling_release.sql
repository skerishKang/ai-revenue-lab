-- #4379: a durable object-metadata row carries no PADIEM byte ceiling. The upper
-- bound shared by 008, 026 and 027 was a product-side capacity claim, not a
-- platform request limit or a Provider limit, so it is released here rather than
-- enlarged. The released migrations are not rewritten: this forward migration
-- rebuilds each table, because SQLite cannot alter a CHECK constraint in place.
-- The non-empty lower bound and every other column, constraint and index are
-- carried over unchanged. Source migration only: applying it to any environment
-- is a separate release action.
PRAGMA foreign_keys=OFF;
PRAGMA defer_foreign_keys=ON;

-- 008 claw_document_metadata: byte_length keeps `> 0` and loses the 10 MiB bound.
CREATE TABLE claw_document_metadata_next (
    document_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length > 0),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    deleted_at TEXT
);

INSERT INTO claw_document_metadata_next
  (document_id,tenant_id,object_key,filename,media_type,byte_length,created_at,expires_at,deleted_at)
SELECT document_id,tenant_id,object_key,filename,media_type,byte_length,created_at,expires_at,deleted_at
FROM claw_document_metadata;

DROP TABLE claw_document_metadata;
ALTER TABLE claw_document_metadata_next RENAME TO claw_document_metadata;

CREATE INDEX IF NOT EXISTS idx_claw_document_metadata_tenant_active
ON claw_document_metadata (tenant_id, deleted_at, expires_at);

-- 026 claw_conversation_artifact_index: size_bytes keeps `> 0` and loses the bound.
CREATE TABLE claw_conversation_artifact_index_next (
    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    workspace_ref TEXT NOT NULL,
    source_run_ref TEXT NOT NULL REFERENCES claw_run_history(run_id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (
        media_type IN (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/pdf'
        )
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    integrity_ref TEXT NOT NULL CHECK (length(integrity_ref) = 64),
    location_kind TEXT NOT NULL,
    location_ref TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO claw_conversation_artifact_index_next
  (ordinal,artifact_id,user_id,conversation_id,workspace_ref,source_run_ref,filename,
   media_type,size_bytes,integrity_ref,location_kind,location_ref,created_at)
SELECT ordinal,artifact_id,user_id,conversation_id,workspace_ref,source_run_ref,filename,
   media_type,size_bytes,integrity_ref,location_kind,location_ref,created_at
FROM claw_conversation_artifact_index;

DROP TABLE claw_conversation_artifact_index;
ALTER TABLE claw_conversation_artifact_index_next RENAME TO claw_conversation_artifact_index;

CREATE INDEX IF NOT EXISTS idx_claw_conversation_artifact_owner
ON claw_conversation_artifact_index (
    user_id, conversation_id, workspace_ref, ordinal DESC
);

-- 027 b66_template_source: byte_length keeps `>= 1` and loses the bound.
CREATE TABLE b66_template_source_next (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/csv')),
    original_filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 1),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploaded', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO b66_template_source_next
  (id,user_id,workspace_id,media_type,original_filename,object_key,byte_length,sha256,
   status,created_at,updated_at)
SELECT id,user_id,workspace_id,media_type,original_filename,object_key,byte_length,sha256,
   status,created_at,updated_at
FROM b66_template_source;

DROP TABLE b66_template_source;
ALTER TABLE b66_template_source_next RENAME TO b66_template_source;

CREATE INDEX IF NOT EXISTS idx_b66_template_source_owner_workspace_status
ON b66_template_source (user_id, workspace_id, status, created_at DESC);

PRAGMA foreign_keys=ON;
