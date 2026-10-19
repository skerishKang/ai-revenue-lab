-- PADIEM Custom (BYOK): owner-scoped provider credentials for the
-- B14-independent direct execution path. Only the sealed AES-GCM envelope is
-- stored; the raw provider key never enters D1 as plaintext.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS chat_custom_provider_credentials (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL,
 key_last4 TEXT NOT NULL,
 sealed_credential TEXT NOT NULL,
 created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL,
 PRIMARY KEY (user_id, provider_id)
);
