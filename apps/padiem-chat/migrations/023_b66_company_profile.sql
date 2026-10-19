-- B66 #3406 — canonical account/workspace-bound company profile.
-- Source migration only. Production apply is a separate release action.
-- Real customer values are runtime data and never belong in this migration.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_company_profile (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    company TEXT,
    representative TEXT,
    contact_person TEXT,
    business_number TEXT,
    address TEXT,
    phone TEXT,
    email TEXT,
    default_validity_days INTEGER CHECK (default_validity_days IS NULL OR (default_validity_days >= 0 AND default_validity_days <= 3650)),
    default_tax_mode TEXT CHECK (default_tax_mode IS NULL OR default_tax_mode IN ('EXCLUSIVE', 'INCLUSIVE', 'EXEMPT')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_b66_company_profile_workspace_updated
ON b66_company_profile (workspace_id, updated_at DESC);
