-- #8192: additive version observations; existing receipts are untouched.
ALTER TABLE mesh_device_helper_ready ADD COLUMN helper_sha256 TEXT;
ALTER TABLE mesh_device_helper_ready ADD COLUMN helper_version TEXT;
ALTER TABLE mesh_device_helper_ready ADD COLUMN mesh_agent_version TEXT;
ALTER TABLE mesh_device_helper_ready ADD COLUMN last_healthy_at TEXT;
