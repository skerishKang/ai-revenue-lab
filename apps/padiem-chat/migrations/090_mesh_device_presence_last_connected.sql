-- #6694 (A) — the PC list shows MeshCentral's real node connectivity, and an
-- offline row names the moment the node was last seen connected.
--
-- `mesh_device_presence` keeps one row per device with the LATEST beat, so a
-- connected=false beat overwrites the moment the node was last actually
-- connected. `last_connected_at` preserves that: the upsert stamps it only on
-- connected beats and keeps the old value otherwise. Additive only.
ALTER TABLE mesh_device_presence ADD COLUMN last_connected_at TEXT;
