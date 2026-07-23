-- Migration 008: Phase 2B web acceptance contracts (additive only).
--
-- Adds:
--  * reader_choices: enforce ONE canon choice per reader. The legacy table
--    constraint UNIQUE(reader_id, canon_episode_id, choice_text) still allowed
--    the same reader to store several choice_text values for one canon episode.
--    A stricter UNIQUE(reader_id, canon_episode_id) index closes that gap so a
--    reader can never hold two choices for the same canon checkpoint.
--
--    If pre-existing rows already violate this (a reader with more than one
--    choice for the same canon episode), CREATE UNIQUE INDEX fails and the
--    migration aborts. This is intentional: duplicate state is surfaced as a
--    migration failure for explicit operator repair and is NEVER silently
--    deleted or arbitrarily resolved.
--  * reader_sessions.last_seen_at / admin_sessions.last_seen_at — idle-expiry
--    tracking, independent of the absolute expires_at.
--
-- No existing column is altered or dropped. No existing migration is modified.

CREATE UNIQUE INDEX IF NOT EXISTS idx_reader_choices_one_per_canon
    ON reader_choices(reader_id, canon_episode_id);

ALTER TABLE reader_sessions ADD COLUMN last_seen_at TEXT;

ALTER TABLE admin_sessions ADD COLUMN last_seen_at TEXT;

PRAGMA user_version = 8;
