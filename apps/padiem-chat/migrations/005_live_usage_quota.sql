-- Business 62 Phase 17: bounded live-AI usage accounting.
-- Stores accounting metadata only. Never store prompts, responses, raw IPs, OAuth tokens,
-- provider credentials, attachments, or upstream payloads in this table.

CREATE TABLE IF NOT EXISTS live_usage_buckets (
    subject_type TEXT NOT NULL CHECK (subject_type IN ('anonymous', 'user', 'global')),
    subject_key TEXT NOT NULL,
    bucket_type TEXT NOT NULL CHECK (bucket_type IN ('minute', 'day', 'global_day')),
    bucket_start TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_key, bucket_type, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_live_usage_buckets_updated_at
    ON live_usage_buckets(updated_at);
