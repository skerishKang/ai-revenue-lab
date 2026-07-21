-- Migration 003: idempotency, continuity, and privacy contracts.
-- Does NOT modify migration 001 or 002 tables.

-- ── Idempotency state machine columns ─────────────────────────────
-- ALTER TABLE branch_generation_requests ADD COLUMN IF NOT EXISTS ...
-- SQLite doesn't support IF NOT EXISTS for columns, so we use pragmatic approach.

-- Add operation_type to branch_generation_requests for resource binding
-- Add attempt_number for retry state transition tracking
-- Add pending_lease_at for stale detection
-- Add updated_at for recovery tracking
ALTER TABLE branch_generation_requests ADD COLUMN operation_type TEXT NOT NULL DEFAULT 'personal_branch';
ALTER TABLE branch_generation_requests ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number >= 1);
ALTER TABLE branch_generation_requests ADD COLUMN pending_lease_at TEXT;
ALTER TABLE branch_generation_requests ADD COLUMN updated_at TEXT;

-- Create index for resource binding queries including operation_type
CREATE INDEX IF NOT EXISTS idx_branch_gen_req_binding ON branch_generation_requests(
    reader_id, reader_choice_id, prior_episode_id,
    canon_checkpoint_id, world_id, operation_type
);

-- ── Pilot evidence category constraints ─────────────────────────────
-- Add nullable FK columns for clearer category-based reference tracking
ALTER TABLE pilot_evidence ADD COLUMN category_consent_obtained INTEGER CHECK(category_consent_obtained IN (0, 1));
ALTER TABLE pilot_evidence ADD COLUMN category_revenue_hypothesis INTEGER CHECK(category_revenue_hypothesis IN (0, 1));

-- ── Reader deletion clean separation ────────────────────────────────
-- Add anonymized_reader_id to branches table for tracking
ALTER TABLE branches ADD COLUMN anonymized_at TEXT;

-- Add applied_choice_id to applied_reader_input tracking
-- Add reader_choice_id to applied_reader_input in episodes is already done via JSON

-- Ensure deletion audit uses privacy-safe identifiers
ALTER TABLE reader_deletion_audit ADD COLUMN deletion_event_id TEXT;

-- Add applied_reader_input.private_text anonymization support
-- via the existing applied_reader_input_json field

-- ── Indexes for performance ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_branch_gen_req_status ON branch_generation_requests(status);
CREATE INDEX IF NOT EXISTS idx_branch_gen_req_updated ON branch_generation_requests(updated_at);
