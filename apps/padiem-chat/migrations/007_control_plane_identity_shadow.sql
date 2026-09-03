-- B62 #1228 — non-authoritative shadow projection of Shared Control Plane identity/session.
-- Source migration only. Applying this migration to any environment is a separate release action.
-- Canonical identity/session truth remains owned by Shared Control Plane.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS control_plane_identity_shadow (
    product_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    canonical_subject_id TEXT NOT NULL,
    auth_session_id TEXT NOT NULL,
    session_revision INTEGER NOT NULL CHECK (session_revision >= 1),
    session_state TEXT NOT NULL CHECK (session_state IN ('active', 'revoked', 'expired')),
    session_expires_at TEXT NOT NULL,
    observed_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_control_plane_identity_shadow_session
    ON control_plane_identity_shadow(auth_session_id);
