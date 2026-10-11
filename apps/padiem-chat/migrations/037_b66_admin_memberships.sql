-- B66 membership / access administration. Dedicated PADIEM_CHAT_DB D1.
-- Existing members stay approved FREE; only new signups require review.
-- Schema apply is an explicit production operation. Do not create an admin from email alone.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS b66_memberships (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','suspended')),
  tier TEXT NOT NULL DEFAULT 'FREE' CHECK (tier IN ('FREE','PLUS','PRO','MAX')),
  revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
  granted_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_b66_memberships_status ON b66_memberships(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS b66_membership_audit (
  audit_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  actor_user_id TEXT NOT NULL REFERENCES users(id),
  previous_status TEXT NOT NULL,
  previous_tier TEXT NOT NULL,
  current_status TEXT NOT NULL,
  current_tier TEXT NOT NULL,
  revision INTEGER NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_b66_membership_audit_user ON b66_membership_audit(user_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS b66_signup_alert_outbox (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  delivered_at TEXT,
  last_attempt_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0)
);

-- Before creating the trigger, preserve existing accounts without disruption.
INSERT OR IGNORE INTO b66_memberships
  (user_id, status, tier, revision, granted_by, created_at, updated_at)
SELECT id, 'approved', 'FREE', 0, NULL, created_at, updated_at FROM users;

CREATE TRIGGER IF NOT EXISTS b66_member_after_signup
AFTER INSERT ON users
BEGIN
  INSERT OR IGNORE INTO b66_memberships
    (user_id, status, tier, revision, granted_by, created_at, updated_at)
  VALUES (NEW.id, 'pending', 'FREE', 0, NULL, NEW.created_at, NEW.created_at);
  INSERT OR IGNORE INTO b66_signup_alert_outbox (user_id, created_at)
  VALUES (NEW.id, NEW.created_at);
END;

-- A tier-to-model policy is a separate reviewed revision; no B14 route is
-- created or modified by these assignments. It starts inactive.
CREATE TABLE IF NOT EXISTS b66_model_access_policy (
  id TEXT PRIMARY KEY CHECK (id='b66'),
  revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0,1)),
  changed_by TEXT,
  updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO b66_model_access_policy (id,revision,active,updated_at)
VALUES ('b66',0,0,'1970-01-01T00:00:00Z');

CREATE TABLE IF NOT EXISTS b66_tier_model_grants (
  tier TEXT NOT NULL CHECK (tier IN ('FREE','PLUS','PRO','MAX')),
  model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 256),
  PRIMARY KEY (tier,model_id)
);
-- Global B66 model switch. An OFF model is unavailable to every tier,
-- even where a prior tier grant still lists it.
CREATE TABLE IF NOT EXISTS b66_disabled_models (
  model_id TEXT PRIMARY KEY CHECK(length(model_id) BETWEEN 1 AND 256)
);
CREATE TABLE IF NOT EXISTS b66_model_policy_audit (
  audit_id TEXT PRIMARY KEY,
  actor_user_id TEXT NOT NULL REFERENCES users(id),
  revision INTEGER NOT NULL,
  active INTEGER NOT NULL,
  changed_at TEXT NOT NULL
);

-- Per-channel receipts; configured alert destinations are server-side only.
CREATE TABLE IF NOT EXISTS b66_signup_alert_delivery (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK(channel IN ('telegram','discord','email')),
  delivered_at TEXT NOT NULL,
  PRIMARY KEY(user_id,channel)
);
