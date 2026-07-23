-- Migration: deactivation_requests table (PostgreSQL)
-- Traveler-operated self-deactivation workflow.

CREATE TABLE IF NOT EXISTS deactivation_requests (
    id          TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    updated_at  TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    FOREIGN KEY (traveler_id) REFERENCES travelers(id)
);
