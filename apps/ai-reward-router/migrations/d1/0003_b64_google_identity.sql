-- B64 Google identities (issue #987, independent-service reuse).
--
-- A Google account is linked to a B64 member by its stable provider subject,
-- never by the email address it happens to present: `google_sub` is the key and
-- one B64 member backs exactly one subject. This is an ADDITIVE table — no
-- column is changed or dropped on `b64_member` or `b64_session`, no existing
-- row is rewritten, and `b64_user_income` is not touched. A member that already
-- signed up with an email and password keeps its own row and its own login path;
-- signing in with Google creates a separate B64 member unless that Google
-- subject was linked before.
--
-- Storing the subject here rather than widening `b64_member` is also what keeps
-- this reuse from becoming a migration of live data.
--
-- D1/SQLite dialect. Replay-safe: every statement is IF NOT EXISTS.
-- Applied ONLY by the dispatch-only B64 D1 provision gate; application code
-- never executes this DDL at runtime.

CREATE TABLE IF NOT EXISTS b64_member_google (
  google_sub TEXT NOT NULL,
  member_id TEXT NOT NULL,
  email TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  PRIMARY KEY (google_sub)
);

-- One B64 member per Google subject, enforced where the link is stored.
CREATE UNIQUE INDEX IF NOT EXISTS idx_b64_member_google_member
  ON b64_member_google (member_id);
