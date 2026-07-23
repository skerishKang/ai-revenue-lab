-- Living Learning PostgreSQL schema: portal identity boundary + review audit.
-- Semantically equivalent to SQLite migrations 009/010 identity/membership/
-- review tables. Idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT ll_now(),
    updated_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_external_identities_provider_issuer_subject
    ON external_identities(provider, issuer, subject);

CREATE TABLE IF NOT EXISTS product_memberships (
    id TEXT PRIMARY KEY,
    external_identity_id TEXT NOT NULL REFERENCES external_identities(id),
    role TEXT NOT NULL CHECK (role IN ('learner', 'operator', 'reviewer')),
    learner_id TEXT REFERENCES learners(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT ll_now(),
    revoked_at TEXT,
    CHECK (
        (role = 'learner' AND learner_id IS NOT NULL)
        OR (role IN ('operator', 'reviewer') AND learner_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_memberships_identity ON product_memberships(external_identity_id);
CREATE INDEX IF NOT EXISTS idx_memberships_learner ON product_memberships(learner_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_memberships_one_active_learner_per_identity
    ON product_memberships(external_identity_id)
    WHERE role = 'learner' AND status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_memberships_one_active_identity_per_learner
    ON product_memberships(learner_id)
    WHERE role = 'learner' AND status = 'active' AND learner_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS lesson_review_events (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    external_identity_id TEXT NOT NULL REFERENCES external_identities(id),
    action TEXT NOT NULL CHECK (action IN ('approved', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE INDEX IF NOT EXISTS idx_review_events_lesson ON lesson_review_events(lesson_id);
