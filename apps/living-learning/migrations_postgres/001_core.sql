-- Living Learning PostgreSQL schema: core aggregate roots.
-- Semantically equivalent to the final SQLite schema produced by migrations/.
-- Timestamps are TEXT ISO-8601 UTC (the app stores/compares opaque strings via
-- ll_now(), matching the SQLite _utcnow format). Boolean-like flags are SMALLINT
-- 0/1. Every statement is idempotent (IF NOT EXISTS) so a fresh run builds the
-- whole schema and a re-run is a no-op.

-- ISO-8601 UTC text timestamp matching the application's _utcnow() format.
CREATE OR REPLACE FUNCTION ll_now() RETURNS TEXT AS $$
    SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
$$ LANGUAGE SQL STABLE;

CREATE TABLE IF NOT EXISTS learners (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '학습자',
    preferred_language TEXT NOT NULL DEFAULT 'ko',
    topic TEXT NOT NULL,
    target_duration_minutes INTEGER NOT NULL DEFAULT 10,
    pacing_feedback_style TEXT NOT NULL DEFAULT 'moderate',
    example_preference TEXT NOT NULL DEFAULT 'code_first',
    theory_density TEXT NOT NULL DEFAULT 'balanced',
    review_question_count INTEGER NOT NULL DEFAULT 3,
    jargon_level TEXT NOT NULL DEFAULT 'simplified',
    interests TEXT NOT NULL DEFAULT '[]',
    exclusions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT ll_now(),
    updated_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS curricula (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0',
    description TEXT NOT NULL DEFAULT '',
    concepts TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curricula(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prerequisites TEXT NOT NULL DEFAULT '[]',
    sequence_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS learner_sessions (
    session_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    curriculum_id TEXT NOT NULL REFERENCES curricula(id),
    current_lesson_sequence INTEGER NOT NULL DEFAULT 0,
    last_activity_at TEXT NOT NULL DEFAULT ll_now(),
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS diagnostic_snapshots (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    coding_experience TEXT NOT NULL DEFAULT 'none',
    explanation_preference TEXT NOT NULL DEFAULT 'balanced',
    theory_practice_balance TEXT NOT NULL DEFAULT 'balanced',
    derived_difficulty TEXT NOT NULL DEFAULT 'intro_1',
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS learning_goals (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    goal_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
    created_at TEXT NOT NULL DEFAULT ll_now(),
    superseded_at TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
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
    source_diagnostic_snapshot_id TEXT REFERENCES diagnostic_snapshots(id),
    source_feedback_id TEXT,
    source_comprehension_response_id TEXT,
    created_at TEXT NOT NULL DEFAULT ll_now(),
    updated_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS exercises (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    question TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    correct_answer TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT 'easy',
    sequence_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS exercise_responses (
    id TEXT PRIMARY KEY,
    exercise_id TEXT NOT NULL REFERENCES exercises(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    selected_answer TEXT NOT NULL DEFAULT '',
    is_correct SMALLINT NOT NULL DEFAULT 0,
    responded_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS comprehension_responses (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    understood SMALLINT NOT NULL DEFAULT 1,
    difficulty_rating INTEGER NOT NULL DEFAULT 3,
    free_text TEXT NOT NULL DEFAULT '',
    response_id TEXT NOT NULL DEFAULT '',
    responded_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    lesson_generation INTEGER NOT NULL DEFAULT 1,
    direction_choices TEXT NOT NULL DEFAULT '[]',
    free_text TEXT NOT NULL DEFAULT '',
    applied_status TEXT NOT NULL DEFAULT 'not_applied' CHECK (applied_status IN ('not_applied', 'applied_to_second')),
    applied_to_lesson_id TEXT REFERENCES lessons(id),
    created_at TEXT NOT NULL DEFAULT ll_now()
);

-- Now that feedback/comprehension exist, add their FKs from lessons.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lessons_source_feedback_id_fkey'
    ) THEN
        ALTER TABLE lessons ADD CONSTRAINT lessons_source_feedback_id_fkey
            FOREIGN KEY (source_feedback_id) REFERENCES feedback(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lessons_source_comprehension_response_id_fkey'
    ) THEN
        ALTER TABLE lessons ADD CONSTRAINT lessons_source_comprehension_response_id_fkey
            FOREIGN KEY (source_comprehension_response_id) REFERENCES comprehension_responses(id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS adaptation_decisions (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    prior_lesson_id TEXT NOT NULL REFERENCES lessons(id),
    next_lesson_id TEXT NOT NULL REFERENCES lessons(id),
    signal_type TEXT NOT NULL,
    signal_reference_id TEXT NOT NULL DEFAULT '',
    dimension TEXT NOT NULL,
    before_value TEXT NOT NULL DEFAULT '',
    after_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS learner_mastery (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    mastery_level TEXT NOT NULL DEFAULT 'unknown',
    practice_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TEXT NOT NULL DEFAULT ll_now(),
    updated_at TEXT NOT NULL DEFAULT ll_now(),
    UNIQUE(learner_id, concept_id)
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    attempt_group_id TEXT NOT NULL DEFAULT '',
    attempt_number INTEGER NOT NULL DEFAULT 1,
    request_id TEXT,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    advertised_model TEXT,
    cost_class TEXT DEFAULT 'free',
    prompt_version TEXT,
    latency_ms DOUBLE PRECISION DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    success SMALLINT NOT NULL DEFAULT 0,
    validation_result TEXT DEFAULT 'pending',
    error_category TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    lesson_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    provider_call_count INTEGER NOT NULL DEFAULT 1,
    latency_ms_total DOUBLE PRECISION NOT NULL DEFAULT 0,
    input_tokens_total INTEGER,
    output_tokens_total INTEGER,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL DEFAULT 'free_sample' CHECK (evidence_type IN ('free_sample', 'pilot_complete', 'beta_access')),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    offer_description TEXT NOT NULL DEFAULT '',
    consent_recorded SMALLINT NOT NULL DEFAULT 0 CHECK (consent_recorded IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT ll_now()
);

CREATE TABLE IF NOT EXISTS idempotency_requests (
    id TEXT PRIMARY KEY,
    key_value TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    learner_id TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'failed_retryable', 'failed_terminal')),
    result_json TEXT DEFAULT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TEXT DEFAULT NULL,
    owner_token TEXT,
    fencing_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ll_now(),
    updated_at TEXT NOT NULL DEFAULT ll_now()
);

-- Indexes (idempotent).
CREATE INDEX IF NOT EXISTS idx_lessons_learner_id ON lessons(learner_id);
CREATE INDEX IF NOT EXISTS idx_lessons_concept_id ON lessons(concept_id);
CREATE INDEX IF NOT EXISTS idx_lessons_generation_status ON lessons(generation_status);
CREATE INDEX IF NOT EXISTS idx_lessons_publication_state ON lessons(publication_state);
CREATE INDEX IF NOT EXISTS idx_lessons_prior_lesson ON lessons(prior_lesson_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_active
    ON lessons (learner_id, concept_id, lesson_number)
    WHERE generation_status != 'generation_failed';

CREATE INDEX IF NOT EXISTS idx_feedback_lesson_id ON feedback(lesson_id);
CREATE INDEX IF NOT EXISTS idx_feedback_learner_id ON feedback(learner_id);
CREATE INDEX IF NOT EXISTS idx_feedback_applied_status ON feedback(applied_status);
CREATE INDEX IF NOT EXISTS idx_feedback_lesson_generation ON feedback(lesson_id, lesson_generation);
CREATE INDEX IF NOT EXISTS idx_feedback_lesson_learner ON feedback(lesson_id, learner_id);

CREATE INDEX IF NOT EXISTS idx_exercises_lesson_id ON exercises(lesson_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exercise_responses_unique ON exercise_responses(exercise_id, learner_id);
CREATE INDEX IF NOT EXISTS idx_comprehension_responses_lesson_id ON comprehension_responses(lesson_id);
CREATE INDEX IF NOT EXISTS idx_comprehension_responses_learner_id ON comprehension_responses(learner_id);
CREATE INDEX IF NOT EXISTS idx_comprehension_lesson_learner ON comprehension_responses(lesson_id, learner_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_learner_mastery_unique ON learner_mastery(learner_id, concept_id);

CREATE INDEX IF NOT EXISTS idx_generation_runs_lesson_id ON generation_runs(lesson_id);
CREATE INDEX IF NOT EXISTS idx_generation_runs_task_type ON generation_runs(task_type);
CREATE INDEX IF NOT EXISTS idx_generation_runs_attempt_group ON generation_runs(attempt_group_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gen_runs_req_id ON generation_runs(request_id) WHERE request_id IS NOT NULL AND request_id != '';

CREATE INDEX IF NOT EXISTS idx_adaptation_learner ON adaptation_decisions(learner_id);
CREATE INDEX IF NOT EXISTS idx_adaptation_next_lesson ON adaptation_decisions(next_lesson_id);

CREATE INDEX IF NOT EXISTS idx_learning_goals_learner ON learning_goals(learner_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_learning_goals_one_active_per_learner
    ON learning_goals(learner_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_diagnostic_snapshots_learner ON diagnostic_snapshots(learner_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_operation_key ON idempotency_requests(key_value);
CREATE INDEX IF NOT EXISTS idx_idempotency_learner ON idempotency_requests(learner_id);

CREATE INDEX IF NOT EXISTS idx_concepts_curriculum_id ON concepts(curriculum_id);
CREATE INDEX IF NOT EXISTS idx_concepts_sequence_order ON concepts(curriculum_id, sequence_order);
CREATE INDEX IF NOT EXISTS idx_learner_sessions_learner_id ON learner_sessions(learner_id);
CREATE INDEX IF NOT EXISTS idx_pilot_evidence_learner_id ON pilot_evidence(learner_id);
CREATE INDEX IF NOT EXISTS idx_pilot_evidence_lesson_id ON pilot_evidence(lesson_id);
