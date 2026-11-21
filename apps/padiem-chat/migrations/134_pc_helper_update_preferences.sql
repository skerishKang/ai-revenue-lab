-- An owner's settings for a single existing PC link; no existing rows rewritten.
ALTER TABLE pc_device_links ADD COLUMN auto_helper_update INTEGER NOT NULL DEFAULT 1 CHECK(auto_helper_update IN (0, 1));
ALTER TABLE pc_device_links ADD COLUMN helper_update_dismissed_version TEXT;
