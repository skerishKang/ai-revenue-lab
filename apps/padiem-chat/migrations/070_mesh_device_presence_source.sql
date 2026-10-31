-- #5553 requirement 6: Broker registration is not a Mesh prerequisite.
-- Rebuild only the presence receipt, preserving every existing 067 row.
CREATE TABLE mesh_device_presence_rebuilt_070 (
  device_id TEXT PRIMARY KEY CHECK(length(device_id) BETWEEN 1 AND 256),
  connected INTEGER NOT NULL CHECK(connected IN (0, 1)),
  received_at TEXT NOT NULL,
  credential_generation INTEGER CHECK(credential_generation IS NULL OR credential_generation BETWEEN 1 AND 1000000),
  source TEXT NOT NULL DEFAULT 'broker' CHECK(source IN ('broker', 'mesh')),
  CHECK(source = 'mesh' OR credential_generation IS NOT NULL)
);
INSERT INTO mesh_device_presence_rebuilt_070
  (device_id, connected, received_at, credential_generation, source)
SELECT device_id, connected, received_at, credential_generation, 'broker'
FROM mesh_device_presence;
DROP TABLE mesh_device_presence;
ALTER TABLE mesh_device_presence_rebuilt_070 RENAME TO mesh_device_presence;
