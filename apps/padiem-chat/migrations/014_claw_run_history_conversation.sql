-- #2829 Phase B: persisted run-to-conversation linkage.
--
-- Additive only. Runtime schema mutation is forbidden; migrations apply this
-- script once to add the nullable canonical conversation reference column
-- to the existing claw_run_history table.
--
-- No new table. No referential constraint. No destructive change.
-- conversation_id authority comes from the existing canonical conversation
-- validation + owner-scoped lookup, not from the database schema.
--
-- Existing rows (legacy) keep NULL and project session:null.

ALTER TABLE claw_run_history ADD COLUMN conversation_id TEXT;
