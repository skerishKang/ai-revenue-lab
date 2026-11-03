-- #6724 MCP PC shell jobs: the durable owner record of one background command.
--
-- A job has no execution deadline (owner decision 2026-10-24), so the handle a
-- caller reads back must outlive the request that started it. This row is that
-- handle: it binds the job id to the account, the PC and the token that started
-- it, so another account or another PC cannot read or stop it by guessing an id.
--
-- The command text and the output are deliberately absent. The command is
-- represented by a SHA-256 digest only; the bytes stay on the PC's own job file
-- and reach Chat through the existing oracle_mesh result store.
CREATE TABLE IF NOT EXISTS padiem_mcp_shell_jobs (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_id TEXT NOT NULL REFERENCES padiem_mcp_tokens(id),
    device_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    dispatch_id TEXT,
    command_sha256 TEXT NOT NULL,
    shell TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','running','exited','cancelled','lost')),
    exit_code INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mcp_shell_jobs_owner ON padiem_mcp_shell_jobs(user_id,device_id,created_at DESC);
