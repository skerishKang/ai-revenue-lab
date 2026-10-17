-- #4647 meeting decisions and follow-up work candidates.
-- Rows are AI/human candidates about a meeting, never an executed Calendar or messaging
-- write. `registered` is reserved for the existing verified Padiem Calendar path (#2834);
-- the meeting record API refuses to set it, so a candidate can never look like a booked
-- appointment here. Grounding is kept as an offset range into the meeting's transcript
-- artifact, so no speech text is duplicated into this database.
-- Application order: after 049 (FK into claw_meetings). Idempotent; 001-048 untouched.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS claw_meeting_actions (
  action_ref TEXT NOT NULL PRIMARY KEY,
  meeting_ref TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('decision','followup')),
  summary TEXT NOT NULL CHECK (length(summary) BETWEEN 1 AND 500),
  owner_label TEXT CHECK (owner_label IS NULL OR length(owner_label) BETWEEN 1 AND 120),
  due_date TEXT CHECK (due_date IS NULL OR length(due_date) = 10),
  status TEXT NOT NULL CHECK (status IN ('candidate','confirmed','dismissed','registered')),
  evidence_offset_start INTEGER,
  evidence_offset_end INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(meeting_ref) REFERENCES claw_meetings(meeting_ref) ON DELETE CASCADE,
  CHECK (evidence_offset_start IS NULL
         OR (evidence_offset_end IS NOT NULL
             AND evidence_offset_start >= 0
             AND evidence_offset_end > evidence_offset_start))
);

CREATE INDEX IF NOT EXISTS idx_claw_meeting_actions_meeting
  ON claw_meeting_actions(user_id, workspace_id, meeting_ref);
