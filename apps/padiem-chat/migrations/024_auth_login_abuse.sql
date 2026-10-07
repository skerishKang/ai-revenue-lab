-- Dedicated password-login abuse-control authority (#3508).
-- Stores only opaque HMAC subject keys and bounded daily counters.
-- Never store raw usernames, emails, IP addresses, passwords, session values,
-- OAuth tokens, or AI quota state in this table.

CREATE TABLE IF NOT EXISTS auth_login_abuse_buckets (
    subject_type TEXT NOT NULL CHECK (subject_type IN ('identifier', 'network', 'global')),
    subject_key TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_key, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_auth_login_abuse_buckets_updated_at
    ON auth_login_abuse_buckets(updated_at);
