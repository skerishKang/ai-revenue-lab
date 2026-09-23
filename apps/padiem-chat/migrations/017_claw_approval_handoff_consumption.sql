-- #2961: consumption fields for the existing owner-scoped approval handoff.
--
-- Additive only, under the same Claw history persistence owner as #2956.
-- No new table, no new store, no referential constraint, no destructive change.
-- This remains NOT an Engine continuation store: it never owns resume/cancel
-- state, never verifies a decision, and never mints continuation_ref or
-- pause_id.
--
-- p01_run_id  : the Engine-issued P01 orchestration run identity already carried
--               by #2946's outcome. Persisting it lets a later decision correlate
--               resume lifecycle events server-side, so the browser-echoed value
--               is never treated as authority.
-- consumed_at : one bounded marker set only after the Engine has proven terminal
--               consumption (commit) or canonical denial. A handoff that was not
--               consumed stays retry-safe. Reuse is impossible once marked.
--
-- Existing rows keep NULL for both. A handoff without p01_run_id cannot be
-- resumed and fails closed at the decision boundary.

ALTER TABLE claw_approval_handoff ADD COLUMN p01_run_id TEXT;
ALTER TABLE claw_approval_handoff ADD COLUMN consumed_at TEXT;
