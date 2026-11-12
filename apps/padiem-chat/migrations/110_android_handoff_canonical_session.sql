-- #7558: the Android handoff keeps the canonical session its Google callback
-- established, so the claimed `padiem_session` cookie is bound to it.
--
-- An authority-backed deployment refuses session cookies without a canonical
-- session id after the H2 transition window (auth.SIDELESS_SESSION_ACCEPTED_UNTIL).
-- The callback already establishes the canonical session for the verified
-- Google profile; this column carries its id from the callback to the claim.
-- NULL on a deployment without the canonical authority (cookie-only mode) and
-- on rows created before this migration.
ALTER TABLE padiem_android_auth_handoffs ADD COLUMN canonical_session_id TEXT;
