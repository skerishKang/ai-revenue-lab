-- B66 #4466/#4412 — one bounded server-owned conversation slot per owner/workspace.
--
-- The slot holds the general/quote conversation mode, the server-validated
-- quote facts collected across turns, and the revision used for duplicate and
-- stale-client handling. It never stores QuoteCore computed totals, provider
-- payloads, raw message logs or CGI template data.
--
-- `revision` is a first-class integer column, not only a field inside
-- state_json: it is the guard a write compares and swaps on, so two concurrent
-- requests built on the same revision can never both commit. It mirrors the
-- state revision and a row whose two disagree is refused on read.
--
-- Numbering: 027 stays reserved for #3925 (template custody, still Draft);
-- 040 is the latest existing migration, so this additive slot is 041.
-- Source migration only: production application requires a separate approved
-- rollout. The existing #028 guided-draft slot and all other tables are
-- untouched.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS b66_ai_conversation (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, workspace_id)
);
