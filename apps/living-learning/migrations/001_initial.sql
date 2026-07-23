-- Living Learning: Phase 1 schema

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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS learner_sessions (
    session_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    curriculum_id TEXT NOT NULL,
    current_lesson_sequence INTEGER NOT NULL DEFAULT 0,
    last_activity_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS curricula (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0',
    description TEXT NOT NULL DEFAULT '',
    concepts TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curricula(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prerequisites TEXT NOT NULL DEFAULT '[]',
    sequence_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    lesson_number INTEGER NOT NULL DEFAULT 1,
    prior_lesson_id TEXT,
    generation_status TEXT NOT NULL DEFAULT 'input_received',
    publication_state TEXT NOT NULL DEFAULT 'pending',
    lesson_plan_json TEXT NOT NULL DEFAULT '{}',
    lesson_content_json TEXT NOT NULL DEFAULT '{}',
    adaptation_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exercise_responses (
    id TEXT PRIMARY KEY,
    exercise_id TEXT NOT NULL REFERENCES exercises(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    selected_answer TEXT NOT NULL DEFAULT '',
    is_correct INTEGER NOT NULL DEFAULT 0,
    responded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comprehension_responses (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    understood INTEGER NOT NULL DEFAULT 1,
    difficulty_rating INTEGER NOT NULL DEFAULT 3,
    free_text TEXT NOT NULL DEFAULT '',
    response_id TEXT NOT NULL DEFAULT '',
    responded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    learner_id TEXT NOT NULL REFERENCES learners(id),
    lesson_generation INTEGER NOT NULL DEFAULT 1,
    direction_choices TEXT NOT NULL DEFAULT '[]',
    free_text TEXT NOT NULL DEFAULT '',
    applied_status TEXT NOT NULL DEFAULT 'not_applied',
    applied_to_lesson_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS adaptation_decisions (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    feedback_id TEXT NOT NULL REFERENCES feedback(id),
    original_lesson_plan_json TEXT NOT NULL DEFAULT '{}',
    adapted_lesson_plan_json TEXT NOT NULL DEFAULT '{}',
    adaptation_type TEXT NOT NULL DEFAULT '[]',
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS learner_mastery (
    id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(id),
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    mastery_level TEXT NOT NULL DEFAULT 'unknown',
    practice_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(learner_id, concept_id)
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'unknown',
    advertised_model TEXT NOT NULL DEFAULT '',
    cost_class TEXT NOT NULL DEFAULT 'free',
    prompt_version TEXT NOT NULL DEFAULT '',
    latency_ms REAL NOT NULL DEFAULT 0.0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    lesson_id TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pilot_evidence (
    id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL DEFAULT 'free_sample',
    learner_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    offer_description TEXT NOT NULL DEFAULT '',
    consent_recorded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key_value TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);