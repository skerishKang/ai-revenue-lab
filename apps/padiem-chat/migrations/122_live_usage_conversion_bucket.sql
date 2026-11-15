-- #7799: the conversion quota writes bucket type 'conversion_day', but the
-- table built by 005 only allows ('minute', 'day', 'global_day'), so every
-- conversion allowance failed its CHECK and every run was refused. SQLite
-- cannot alter a CHECK in place, so the table is rebuilt with the conversion
-- bucket admitted. Every other column, constraint and index is carried over
-- unchanged; existing counter rows are preserved.
-- Source migration only: applying it to any environment is a separate release action.
PRAGMA foreign_keys=OFF;
PRAGMA defer_foreign_keys=ON;

CREATE TABLE live_usage_buckets_next (
    subject_type TEXT NOT NULL CHECK (subject_type IN ('anonymous', 'user', 'global')),
    subject_key TEXT NOT NULL,
    bucket_type TEXT NOT NULL CHECK (bucket_type IN ('minute', 'day', 'global_day', 'conversion_day')),
    bucket_start TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_key, bucket_type, bucket_start)
);

INSERT INTO live_usage_buckets_next
  (subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at)
SELECT subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at
FROM live_usage_buckets;

DROP TABLE live_usage_buckets;
ALTER TABLE live_usage_buckets_next RENAME TO live_usage_buckets;

CREATE INDEX IF NOT EXISTS idx_live_usage_buckets_updated_at
ON live_usage_buckets(updated_at);

PRAGMA foreign_keys=ON;
