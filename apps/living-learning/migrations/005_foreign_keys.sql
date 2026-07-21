-- Living Learning: Phase 1 schema integrity migration
PRAGMA foreign_keys=OFF;

BEGIN TRANSACTION;

-- Table lessons: add foreign key for prior_lesson_id
CREATE TABLE IF NOT EXISTS lessons_new (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    lesson_number INTEGER NOT NULL DEFAULT 1,
    prior_lesson_id TEXT REFERENCES lessons(id),
    generation_status TEXT NOT NULL DEFAULT 'input_received',
    publication_state TEXT NOT NULL DEFAULT 'pending',
    lesson_plan_json TEXT NOT NULL DEFAULT '{}',
    lesson_content_json TEXT NOT NULL DEFAULT '{}',
    adaptation_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Note: prior_lesson_id might be '' in existing data, set to NULL if empty to satisfy FK
INSERT INTO lessons_new 
SELECT id, learner_id, concept_id, lesson_number, CASE WHEN prior_lesson_id = '' THEN NULL ELSE prior_lesson_id END, generation_status, publication_state, lesson_plan_json, lesson_content_json, adaptation_summary, created_at, updated_at 
FROM lessons;

DROP TABLE lessons;
ALTER TABLE lessons_new RENAME TO lessons;

-- Table feedback: add foreign key for applied_to_lesson_id
CREATE TABLE IF NOT EXISTS feedback_new (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    lesson_generation INTEGER NOT NULL DEFAULT 1,
    direction_choices TEXT NOT NULL DEFAULT '[]',
    free_text TEXT NOT NULL DEFAULT '',
    applied_status TEXT NOT NULL DEFAULT 'not_applied',
    applied_to_lesson_id TEXT REFERENCES lessons(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO feedback_new 
SELECT id, lesson_id, learner_id, lesson_generation, direction_choices, free_text, applied_status, CASE WHEN applied_to_lesson_id = '' THEN NULL ELSE applied_to_lesson_id END, created_at 
FROM feedback;

DROP TABLE feedback;
ALTER TABLE feedback_new RENAME TO feedback;

-- Table pilot_evidence: add foreign keys for learner_id and lesson_id
CREATE TABLE IF NOT EXISTS pilot_evidence_new (
    id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL DEFAULT 'free_sample',
    learner_id TEXT NOT NULL REFERENCES learners(id),
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    offer_description TEXT NOT NULL DEFAULT '',
    consent_recorded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO pilot_evidence_new 
SELECT * FROM pilot_evidence;

DROP TABLE pilot_evidence;
ALTER TABLE pilot_evidence_new RENAME TO pilot_evidence;

CREATE INDEX IF NOT EXISTS idx_lessons_learner_id ON lessons(learner_id);
CREATE INDEX IF NOT EXISTS idx_lessons_concept_id ON lessons(concept_id);
CREATE INDEX IF NOT EXISTS idx_lessons_generation_status ON lessons(generation_status);
CREATE INDEX IF NOT EXISTS idx_lessons_publication_state ON lessons(publication_state);
CREATE INDEX IF NOT EXISTS idx_lessons_prior_lesson ON lessons(prior_lesson_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_active ON lessons (learner_id, concept_id, lesson_number) WHERE generation_status != 'generation_failed';

CREATE INDEX IF NOT EXISTS idx_feedback_lesson_id ON feedback(lesson_id);
CREATE INDEX IF NOT EXISTS idx_feedback_learner_id ON feedback(learner_id);
CREATE INDEX IF NOT EXISTS idx_feedback_applied_status ON feedback(applied_status);
CREATE INDEX IF NOT EXISTS idx_feedback_lesson_generation ON feedback(lesson_id, lesson_generation);
CREATE INDEX IF NOT EXISTS idx_feedback_lesson_learner ON feedback (lesson_id, learner_id);

CREATE INDEX IF NOT EXISTS idx_pilot_evidence_learner_id ON pilot_evidence(learner_id);
CREATE INDEX IF NOT EXISTS idx_pilot_evidence_lesson_id ON pilot_evidence(lesson_id);

COMMIT;

PRAGMA foreign_keys=ON;
