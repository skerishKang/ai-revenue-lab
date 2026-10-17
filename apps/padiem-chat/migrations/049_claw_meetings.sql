-- #4647 Claw meeting session ledger — additive, owner/workspace scoped metadata only.
-- Original audio and transcripts live in the signed-in user's own Google Drive or the
-- browser (docs/operations/PADIEM_MEETING_RECORDING_STT_DRIVE_20261015.md §4); this table
-- stores no media bytes, no Drive capability and no OAuth material.
-- Application order: 049 -> 050 -> 051 (050/051 have FKs into this table).
-- Idempotent (IF NOT EXISTS). Migrations 001-048 are not modified by this change.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS claw_meetings (
  meeting_ref TEXT NOT NULL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  mode TEXT NOT NULL CHECK (mode IN ('record','transcribe','both')),
  status TEXT NOT NULL CHECK (status IN ('active','ended','discarded')),
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (ended_at IS NULL OR started_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_claw_meetings_recent
  ON claw_meetings(user_id, workspace_id, updated_at DESC);
