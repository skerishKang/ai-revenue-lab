-- B64 members and sessions (issue #987, owner boundary decision 2026-10-27).
--
-- B64 is an independent business of ai-revenue-lab, so its accounts are its
-- own: this schema holds the member credential and the live session row that
-- makes logout and revocation take effect. It adds tables only —
-- 0001_b64_user_income.sql and every existing row are untouched, and income
-- records keep their existing user_id column, which now stores a b64m_ member
-- id for new members.
--
-- D1/SQLite dialect. Replay-safe: every statement is IF NOT EXISTS.
-- Applied ONLY by the dispatch-only B64 D1 provision gate
-- (.github/workflows/b64-d1-provision-gate.yml); application code never
-- executes this DDL at runtime.

CREATE TABLE IF NOT EXISTS b64_member (
  id TEXT NOT NULL,
  email TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS b64_session (
  id TEXT NOT NULL,
  member_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  PRIMARY KEY (id)
);

-- Revocation and login lookups are both by session id (the primary key); this
-- covers the other direction — everything one member has open — without ever
-- scanning another member's rows.
CREATE INDEX IF NOT EXISTS idx_b64_session_member ON b64_session (member_id);
