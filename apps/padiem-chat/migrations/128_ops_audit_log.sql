-- #8035 ②: the operations audit trail — who did what, when, from inside the
-- ops center and from the operations tools. One row per administrator action
-- (feedback status/reply/AI-tester marking) and per member-detail opening.
-- The actor is the signed-in administrator's session user id, or the
-- operations tool's fixed principal when the write came from a tool.
CREATE TABLE IF NOT EXISTS ops_audit_log (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL CHECK(length(actor_user_id) BETWEEN 1 AND 256),
    action TEXT NOT NULL CHECK(length(action) BETWEEN 1 AND 64),
    target_type TEXT NOT NULL CHECK(length(target_type) BETWEEN 1 AND 32),
    target_id TEXT NOT NULL CHECK(length(target_id) BETWEEN 1 AND 256),
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(length(detail_json) <= 4096),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ops_audit_log_created ON ops_audit_log (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_ops_audit_log_target ON ops_audit_log (target_type, target_id, created_at DESC);
