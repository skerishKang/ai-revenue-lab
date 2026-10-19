-- #5015: owner/workspace-scoped preferred PC target.
--
-- This row is a PREFERENCE, never an execution grant. The canonical Broker
-- directory and the deployment Mesh target are re-read on every request that
-- can execute; a stale/revoked/foreign selection must not be used, and another
-- PC is never substituted silently.
--
-- Apply via the separately approved D1 migration gate against the canonical
-- PADIEM_CHAT_DB. No device, account, credential or consent is minted here.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS claw_pc_device_selection (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL CHECK(length(workspace_id) BETWEEN 1 AND 160),
  device_id TEXT NOT NULL CHECK(length(device_id) BETWEEN 1 AND 128),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(user_id, workspace_id)
);
