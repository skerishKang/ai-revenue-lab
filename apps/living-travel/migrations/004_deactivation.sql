-- Migration: Add deactivation_requests table for traveler-operated self-deactivation workflow.

CREATE TABLE IF NOT EXISTS deactivation_requests (
    id          TEXT PRIMARY KEY,
    traveler_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (traveler_id) REFERENCES travelers(id)
);
