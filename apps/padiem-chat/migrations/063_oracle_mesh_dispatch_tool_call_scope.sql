-- #5015: one owner run may stage more than one trusted PC file tool call.
-- 047 declared UNIQUE (user_id, run_id), so a run that lists a directory and
-- then reads a file could never store its second dispatch: the correlation
-- lookup in HistoryStore.create_oracle_mesh_dispatch keys a trusted file call
-- by (user_id, run_id, tool_request_ref), finds nothing for the second call,
-- and the INSERT is then refused by the one-per-run constraint.
--
-- The constraint is not dropped and it is not replaced by a three-column
-- UNIQUE: the legacy single-command lane mints a fresh random
-- tool_request_ref for every staging, so (user_id, run_id, tool_request_ref)
-- would stop guarding it and a retried command could execute twice. Instead
-- the row records which scope it belongs to:
--
--   tool_call_ref NULL      -> legacy one-dispatch-per-run lane (047 rule)
--   tool_call_ref NOT NULL  -> one dispatch per trusted tool call (new rule)
--
-- Each rule is a partial unique index over exactly the rows it owns, so the
-- legacy guard stays byte-for-byte equivalent to 047 and a run can hold one
-- legacy dispatch plus one dispatch per tool call. A third, unpartial index
-- keys a call by its request reference across every row: a Worker that still
-- writes the pre-063 shape (scope NULL) and one that writes the new shape can
-- therefore never stage the same call twice.
--
-- This is a forward rebuild because SQLite cannot alter a table constraint in
-- place. Every column added by 048 (kind, command_text) and 049 (termination,
-- exit_code) is carried over, as are dispatch_id, state, nonce_sha256,
-- result_sha256, result_bytes, expires_at and created_at. Every existing row
-- is copied with tool_call_ref NULL: before this migration at most one row
-- existed per (user_id, run_id), so the legacy partial index is satisfied
-- exactly and no existing dispatch, id, state or result digest changes.
-- A row that was already handed to the executor or already returned a result
-- keeps its nonce/state/digest untouched, so re-staging the same legacy run
-- still refuses instead of executing again.
--
-- Source migration only: applying it to any database is a separate release
-- action.
PRAGMA foreign_keys=OFF;
PRAGMA defer_foreign_keys=ON;

CREATE TABLE oracle_mesh_dispatch_next (
    dispatch_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    tool_request_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    evidence_ref TEXT,
    request_fingerprint TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    device_id TEXT NOT NULL,
    binding_ref TEXT,
    node_ref TEXT NOT NULL,
    root_ref TEXT NOT NULL,
    path_relative TEXT NOT NULL,
    file_path TEXT NOT NULL,
    nonce_sha256 TEXT,
    state TEXT NOT NULL,
    result_sha256 TEXT,
    result_bytes INTEGER,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'read',
    command_text TEXT,
    termination TEXT,
    exit_code INTEGER,
    -- NULL means the 047 run scope; a value is the trusted tool call the
    -- dispatch belongs to.
    tool_call_ref TEXT
);

INSERT INTO oracle_mesh_dispatch_next
  (dispatch_id,user_id,run_id,command_id,tool_request_ref,request_id,revision_ref,
   evidence_ref,request_fingerprint,account_ref,workspace_ref,device_id,binding_ref,
   node_ref,root_ref,path_relative,file_path,nonce_sha256,state,result_sha256,
   result_bytes,expires_at,created_at,kind,command_text,termination,exit_code,
   tool_call_ref)
SELECT dispatch_id,user_id,run_id,command_id,tool_request_ref,request_id,revision_ref,
   evidence_ref,request_fingerprint,account_ref,workspace_ref,device_id,binding_ref,
   node_ref,root_ref,path_relative,file_path,nonce_sha256,state,result_sha256,
   result_bytes,expires_at,created_at,kind,command_text,termination,exit_code,
   NULL
FROM oracle_mesh_dispatch;

DROP TABLE oracle_mesh_dispatch;
ALTER TABLE oracle_mesh_dispatch_next RENAME TO oracle_mesh_dispatch;

CREATE INDEX IF NOT EXISTS idx_oracle_mesh_dispatch_state_expiry
ON oracle_mesh_dispatch (state, expires_at);

-- 047 rule, unchanged: at most one run-scoped dispatch per owner run.
CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_mesh_dispatch_run_scope
ON oracle_mesh_dispatch (user_id, run_id)
WHERE tool_call_ref IS NULL;

-- New rule: at most one dispatch per trusted tool call inside a run.
CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_mesh_dispatch_tool_call
ON oracle_mesh_dispatch (user_id, run_id, tool_call_ref)
WHERE tool_call_ref IS NOT NULL;

-- Cross-form rule: one call is one row whatever scope wrote it. A Worker that
-- has not picked up the scope column writes the same call with tool_call_ref
-- NULL; without this index the same call could exist once in each form and a
-- restart could execute it twice. It also covers every pre-063 row, which has
-- no scope value, so an existing dispatch is never re-created by the new code.
CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_mesh_dispatch_tool_request
ON oracle_mesh_dispatch (user_id, run_id, tool_request_ref);

PRAGMA foreign_keys=ON;
