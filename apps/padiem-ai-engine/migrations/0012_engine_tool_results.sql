-- #4379: durable owner of settled Agent tool results.
-- The Agent runtime keeps only a small reference per result; the payload
-- lives here, so a long run does not retain every tool output in the Worker.
-- Source migration only; applying it to any environment is a separate release
-- action (D1 provision gate). No Worker route provisions schema.
--
-- The reference is server-minted and scoped to one run and owner. A row never
-- exposes a storage locator and the payload column carries the exact original
-- result, so nothing is truncated or kept only partially.
CREATE TABLE IF NOT EXISTS padiem_engine_tool_results_v1 (
    result_ref TEXT NOT NULL,
    run_id TEXT NOT NULL,
    owner_scope TEXT NOT NULL,
    step_index INTEGER NOT NULL CHECK(step_index>=1),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    tool_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (result_ref)
);

CREATE INDEX IF NOT EXISTS idx_engine_tool_results_run
    ON padiem_engine_tool_results_v1(run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_engine_tool_results_expiry
    ON padiem_engine_tool_results_v1(expires_at);
