-- #2833 S2F3A: workspace linkage for the canonical Claw run-history authority.
--
-- Additive only. Runtime schema mutation is forbidden; migrations apply this
-- script once to add the nullable workspace reference column to the existing
-- claw_run_history table.
--
-- No new table. No referential constraint. No destructive change.
-- workspace_id authority comes from the canonical workspace safe-id grammar and
-- the owner-scoped write path, not from a database constraint.
--
-- Existing rows (legacy) keep NULL. A legacy NULL row is never mixed into a
-- tenant workspace filter result.

ALTER TABLE claw_run_history ADD COLUMN workspace_id TEXT;
