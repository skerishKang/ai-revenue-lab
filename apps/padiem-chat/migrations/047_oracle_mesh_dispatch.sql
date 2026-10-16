-- #4139 Oracle management-host MeshCentral read dispatch.
-- One server-minted execution per owner run: the Chat intent route stages the
-- exact broker-bound correlation plus the deployment-verified Mesh target and
-- a nonce hash; the Oracle executor claims it once over the deployment
-- channel secret, executes, and submits the result with the nonce. The nonce
-- itself is never stored — only its SHA-256 — so a database read cannot replay
-- an execution. Expired or consumed rows stay fail-closed; they are never
-- deleted by the application (retention follows the existing D1 policy).
CREATE TABLE IF NOT EXISTS oracle_mesh_dispatch (
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
    -- Nullable on purpose. A PC that never completed the native PC offer has
    -- no Broker binding and no Broker-minted evidence; both stay NULL so no
    -- fabricated reference can ever read as a real one.
    binding_ref TEXT,
    node_ref TEXT NOT NULL,
    root_ref TEXT NOT NULL,
    path_relative TEXT NOT NULL,
    file_path TEXT NOT NULL,
    nonce_sha256 TEXT,
    state TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_oracle_mesh_dispatch_state_expiry
ON oracle_mesh_dispatch (state, expires_at);
