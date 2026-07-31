-- Migration 007
-- The request_id was already added in 003_attempts.sql by a previous agent.
-- ALTER TABLE generation_runs ADD COLUMN request_id TEXT;
SELECT 1;
