-- Living Travel: Phase 1 audit constraints (PostgreSQL)
-- Unique edition number per traveler (prevents duplicate editions on retry).
CREATE UNIQUE INDEX IF NOT EXISTS idx_editions_traveler_number
    ON editions(traveler_id, edition_number);
