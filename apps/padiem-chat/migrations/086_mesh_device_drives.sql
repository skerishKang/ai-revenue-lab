-- #6460: latest authenticated full drive snapshot, owned by the COM2 Mesh queue.
-- Inventory is display metadata; this table never grants a filesystem root.
CREATE TABLE IF NOT EXISTS mesh_device_drives (
  device_id TEXT PRIMARY KEY CHECK(length(device_id) BETWEEN 1 AND 256),
  drives_json TEXT NOT NULL,
  received_at TEXT NOT NULL
);
