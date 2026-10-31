-- #5553 Mesh device presence receipt.
--
-- One row per PC: the last server-recorded Mesh connection observation for a
-- device. The executor poll writes it; the canonical local-access authority
-- reads it as one ONLINE evidence kind (#5695). The row is written only after
-- the server itself resolves the canonical device id from the deployment
-- ownership map and stamps the device's current Broker credential generation,
-- so neither identity nor generation is ever supplied by the request.
--
-- Additive only. Apply via the separately approved D1 migration gate against
-- the canonical PADIEM_CHAT_DB. No device, account or credential is minted.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS mesh_device_presence (
  device_id TEXT PRIMARY KEY CHECK(length(device_id) BETWEEN 1 AND 256),
  connected INTEGER NOT NULL CHECK(connected IN (0, 1)),
  received_at TEXT NOT NULL,
  credential_generation INTEGER NOT NULL CHECK(credential_generation BETWEEN 1 AND 1000000)
);
