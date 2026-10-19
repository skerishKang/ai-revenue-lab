-- #5118 integrated administrator roles over the existing PADIEM_CHAT_DB.
--
-- Reuses the canonical users rows and the existing signed product session.
-- No second account store, password, or login system is introduced. A role is
-- bound to the server-verified canonical user id, never to an email string.
--
-- Applying this migration is a separate release action. Source presence is not
-- evidence that any environment has the table or that a role was granted.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS platform_admin_roles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'SUPER_ADMIN')),
    granted_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_admin_roles_role
ON platform_admin_roles (role);

-- No foreign keys here: the audit keeps the before/after record even if the
-- target account is later removed from the product database.
CREATE TABLE IF NOT EXISTS platform_admin_role_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_user_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    previous_role TEXT CHECK (previous_role IS NULL OR previous_role IN ('ADMIN', 'SUPER_ADMIN')),
    current_role TEXT CHECK (current_role IS NULL OR current_role IN ('ADMIN', 'SUPER_ADMIN')),
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_admin_role_audit_target
ON platform_admin_role_audit (target_user_id, changed_at DESC);
