-- #8359: remember unverified watcher/updater probes without raw PC IDs.
-- One audit/ops alert per continuous (>24h) unresolved episode.
CREATE TABLE IF NOT EXISTS pc_maintenance_probe_needed (
    device_hash TEXT PRIMARY KEY CHECK (length(device_hash)=64),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    notified_at TEXT
);
