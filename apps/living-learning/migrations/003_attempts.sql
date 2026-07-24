-- Living Learning: Phase 1 Migration 003

ALTER TABLE generation_runs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE generation_runs ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
