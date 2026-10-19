-- B66 #3396 — one bounded in-progress guided session per server-derived owner/workspace.
-- #3925 reserves 027 for template custody (still Draft); do not reuse it here.
-- Source migration only: production application requires a separate approved rollout.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS b66_guided_draft (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, workspace_id)
);
