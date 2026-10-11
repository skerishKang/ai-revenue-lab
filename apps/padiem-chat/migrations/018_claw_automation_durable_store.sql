-- #2983 S2F6A: durable D1 persistence for the canonical Claw automation store.
--
-- Additive only, under the existing PADIEM_CHAT_DB persistence owner. No new
-- database, no new binding, no cron trigger, no scheduler table, no lock table
-- and no second dedup table are introduced here.
--
-- This migration does NOT redefine the Claw domain. It materialises the SAME
-- logical entities the reference durable store already owns
-- (kagent.claw_automation.SqliteClawAutomationStore), with the same column
-- names, the same column order and the same value spaces, so the Worker D1
-- adapter and the SQLite reference share ONE domain contract and one set of
-- semantics instead of drifting into two.
--
-- Runtime CREATE TABLE / ALTER TABLE / CREATE INDEX / DROP TABLE stays
-- forbidden: migrations apply this file and the adapter never executes DDL.
--
-- Tables:
--   claw_rules        one row per automation rule (rule_id is the only rule PK)
--   claw_runs         one row per canonical scheduled run (run_id is the only PK)
--   claw_occurrences  the ONLY occurrence dedup authority (occurrence_key PK)
--   claw_proposals    notification proposals materialised by a terminal run
--
-- The occurrence primary key is the single dedup authority: whichever writer
-- wins the claim owns the canonical run for that logical occurrence, so
-- ONE_OCCURRENCE_MAX_CANONICAL_RUNS stays 1 without a lock table or claim token.
--
-- Execution claim reuses the EXISTING claw_runs.status column: PENDING ->
-- RUNNING is one bounded conditional UPDATE on the row the durable tick already
-- claimed. No status column is added and no separate claim row is minted.
--
-- No secret, raw prompt, raw body, OAuth token or cookie column is stored here.
-- The rule payload column carries bounded, already-redacted contract text only.

CREATE TABLE IF NOT EXISTS claw_rules (
    rule_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    schedule_expression TEXT NOT NULL,
    schedule_timezone TEXT NOT NULL,
    target_source TEXT NOT NULL,
    output_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    notification_channels TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claw_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    status TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    output TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS claw_occurrences (
    occurrence_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claw_proposals (
    proposal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    approval_required INTEGER NOT NULL DEFAULT 1,
    approval_reason TEXT NOT NULL DEFAULT '',
    suggested_action TEXT NOT NULL DEFAULT '',
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL
);

-- Every list surface this adapter exposes is workspace-scoped, so the indexes
-- keep each read inside one workspace instead of scanning across tenants.
-- idx_claw_runs_workspace_status also carries the PENDING recovery scan.
CREATE INDEX IF NOT EXISTS idx_claw_rules_workspace
    ON claw_rules (workspace_id);
CREATE INDEX IF NOT EXISTS idx_claw_runs_workspace_status
    ON claw_runs (workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_claw_occurrences_workspace
    ON claw_occurrences (workspace_id);
CREATE INDEX IF NOT EXISTS idx_claw_proposals_workspace
    ON claw_proposals (workspace_id);
