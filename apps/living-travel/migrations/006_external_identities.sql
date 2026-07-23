-- Phase C: external identity mapping (SQLite)
-- Maps a verified external identity provider subject (e.g. Firebase UID) to an
-- optional internal traveler and/or operator principal. An identity may be
-- linked to at most one of traveler/operator (enforced by CHECK).

CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    principal_type TEXT NOT NULL DEFAULT 'pending',
    traveler_id TEXT,
    operator_id TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (traveler_id) REFERENCES travelers(id),
    CHECK (traveler_id IS NULL OR operator_id IS NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_external_identities_provider_subject
    ON external_identities(provider, subject);

CREATE INDEX IF NOT EXISTS idx_external_identities_traveler
    ON external_identities(traveler_id);
