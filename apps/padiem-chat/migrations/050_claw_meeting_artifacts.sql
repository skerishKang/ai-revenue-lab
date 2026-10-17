-- #4647 meeting artifact references — where each meeting output is kept, not the output itself.
-- One audio / one transcript / one minutes row per meeting. `drive_file_id` is the opaque
-- Google Drive file id returned by the browser's own resumable upload receipt; a session URI,
-- bearer token or refresh token must never be stored here.
-- `local_only` is the truthful state while the user has only a browser-side Blob/download,
-- and no Drive deletion is ever implied by removing this row.
-- Application order: after 049 (FK into claw_meetings). Idempotent; 001-048 untouched.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS claw_meeting_artifacts (
  artifact_ref TEXT NOT NULL PRIMARY KEY,
  meeting_ref TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('audio','transcript','minutes')),
  state TEXT NOT NULL CHECK (state IN ('local_only','drive_saved','drive_failed')),
  drive_file_id TEXT,
  filename TEXT NOT NULL CHECK (length(filename) BETWEEN 1 AND 200),
  mime_type TEXT,
  byte_size INTEGER CHECK (byte_size IS NULL OR byte_size BETWEEN 1 AND 188743680),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(meeting_ref) REFERENCES claw_meetings(meeting_ref) ON DELETE CASCADE,
  UNIQUE(meeting_ref, kind),
  CHECK ((state = 'drive_saved') = (drive_file_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_claw_meeting_artifacts_meeting
  ON claw_meeting_artifacts(user_id, workspace_id, meeting_ref);
