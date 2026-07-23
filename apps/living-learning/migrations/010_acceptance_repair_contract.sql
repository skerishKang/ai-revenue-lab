-- Migration 010: acceptance-repair contract.
-- ADDITIVE ONLY — does not modify migrations 001..009.
--
--   * idempotency_requests: owner_token + fencing_version for stale-owner fencing
--   * lessons: publication_state CHECK (review-before-delivery states)
--   * lesson_review_events: operator approve/reject audit trail
--   * learning_goals / diagnostic_snapshots: persisted learner history
--   * product_memberships: role/learner_id invariants + one-active-learner rules

PRAGMA foreign_keys=OFF;

-- ---------------------------------------------------------------------------
-- 1. Idempotency stale-owner fencing.
--    owner_token: fresh CSPRNG value on every acquire/reclaim.
--    fencing_version: 1 on first claim, +1 on each reclaim.
-- ---------------------------------------------------------------------------
ALTER TABLE idempotency_requests ADD COLUMN owner_token TEXT;
ALTER TABLE idempotency_requests ADD COLUMN fencing_version INTEGER NOT NULL DEFAULT 1;

-- ---------------------------------------------------------------------------
-- 2. Lessons: bound publication_state to the review-before-delivery states.
--    Rebuild preserves every column and the active-lesson partial unique index.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lessons_new (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    lesson_number INTEGER NOT NULL DEFAULT 1,
    prior_lesson_id TEXT REFERENCES lessons(id),
    generation_status TEXT NOT NULL DEFAULT 'input_received'
        CHECK (generation_status IN ('input_received', 'generation_pending', 'generation_failed', 'pending_review', 'published', 'closed')),
    publication_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (publication_state IN ('pending', 'published', 'rejected', 'closed')),
    lesson_plan_json TEXT NOT NULL DEFAULT '{}',
    lesson_content_json TEXT NOT NULL DEFAULT '{}',
    adaptation_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO lessons_new
    (id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status,
     publication_state, lesson_plan_json, lesson_content_json, adaptation_summary,
     created_at, updated_at)
SELECT
    id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status,
    publication_state, lesson_plan_json, lesson_content_json, adaptation_summary,
    created_at, updated_at
FROM lessons;

DROP TABLE lessons;
ALTER TABLE lessons_new RENAME TO lessons;

CREATE INDEX IF NOT EXISTS idx_lessons_learner_id ON lessons(learner_id);
CREATE INDEX IF NOT EXISTS idx_lessons_concept_id ON lessons(concept_id);
CREATE INDEX IF NOT EXISTS idx_lessons_generation_status ON lessons(generation_status);
CREATE INDEX IF NOT EXISTS idx_lessons_publication_state ON lessons(publication_state);
CREATE INDEX IF NOT EXISTS idx_lessons_prior_lesson ON lessons(prior_lesson_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_active
    ON lessons (learner_id, concept_id, lesson_number)
    WHERE generation_status != 'generation_failed';

-- ---------------------------------------------------------------------------
-- 3. Review audit trail. The state transition and this insert happen in one
--    transaction at the service layer.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lesson_review_events (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    external_identity_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('approved', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_review_events_lesson ON lesson_review_events(lesson_id);

-- ---------------------------------------------------------------------------
-- 4. Learner history: goals (superseded on replace) and immutable diagnostic
--    snapshots (adaptation provenance).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_goals (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    goal_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_learning_goals_learner ON learning_goals(learner_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_learning_goals_one_active_per_learner
    ON learning_goals(learner_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS diagnostic_snapshots (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    coding_experience TEXT NOT NULL DEFAULT 'none',
    explanation_preference TEXT NOT NULL DEFAULT 'balanced',
    theory_practice_balance TEXT NOT NULL DEFAULT 'balanced',
    derived_difficulty TEXT NOT NULL DEFAULT 'intro_1',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_snapshots_learner ON diagnostic_snapshots(learner_id);

-- ---------------------------------------------------------------------------
-- 5. Membership invariants.
--    learner  => learner_id NOT NULL
--    operator/reviewer => learner_id IS NULL
--    Plus one active learner membership per identity and per learner.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_memberships_new (
    id TEXT PRIMARY KEY,
    external_identity_id TEXT NOT NULL REFERENCES external_identities(id),
    role TEXT NOT NULL CHECK (role IN ('learner', 'operator', 'reviewer')),
    learner_id TEXT REFERENCES learners(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    revoked_at TEXT,
    CHECK (
        (role = 'learner' AND learner_id IS NOT NULL)
        OR (role IN ('operator', 'reviewer') AND learner_id IS NULL)
    )
);

INSERT OR IGNORE INTO product_memberships_new
    (id, external_identity_id, role, learner_id, status, created_at, revoked_at)
SELECT id, external_identity_id, role, learner_id, status, created_at, revoked_at
FROM product_memberships;

DROP TABLE product_memberships;
ALTER TABLE product_memberships_new RENAME TO product_memberships;

CREATE INDEX IF NOT EXISTS idx_memberships_identity ON product_memberships(external_identity_id);
CREATE INDEX IF NOT EXISTS idx_memberships_learner ON product_memberships(learner_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_memberships_one_active_learner_per_identity
    ON product_memberships(external_identity_id)
    WHERE role = 'learner' AND status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_memberships_one_active_identity_per_learner
    ON product_memberships(learner_id)
    WHERE role = 'learner' AND status = 'active' AND learner_id IS NOT NULL;

PRAGMA foreign_keys=ON;
