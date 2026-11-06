-- Durable receiver-side replay protection for signed password auth RPCs.
CREATE TABLE IF NOT EXISTS password_rpc_service_ids (
    service_id TEXT PRIMARY KEY,
    expires TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_rpc_service_ids_expires
    ON password_rpc_service_ids(expires);
