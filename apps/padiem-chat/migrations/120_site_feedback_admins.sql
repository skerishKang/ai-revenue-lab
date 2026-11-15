-- Site feedback administrators (issue #7690 stage 2): which account may read
-- which site's feedback. One account may hold several sites. Designation and
-- removal stay with the central administrator through the ops tool; no web
-- route writes this table.
CREATE TABLE IF NOT EXISTS site_feedback_admins (
    user_id TEXT NOT NULL,
    site TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, site)
);
