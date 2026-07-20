-- Living Learning: Phase 1 constraints

CREATE INDEX IF NOT EXISTS idx_lessons_learner_id ON lessons(learner_id);
CREATE INDEX IF NOT EXISTS idx_lessons_concept_id ON lessons(concept_id);
CREATE INDEX IF NOT EXISTS idx_lessons_generation_status ON lessons(generation_status);
CREATE INDEX IF NOT EXISTS idx_feedback_lesson_id ON feedback(lesson_id);
CREATE INDEX IF NOT EXISTS idx_feedback_learner_id ON feedback(learner_id);
CREATE INDEX IF NOT EXISTS idx_feedback_applied_status ON feedback(applied_status);
CREATE INDEX IF NOT EXISTS idx_exercises_lesson_id ON exercises(lesson_id);
CREATE INDEX IF NOT EXISTS idx_exercise_responses_exercise_id ON exercise_responses(exercise_id);
CREATE INDEX IF NOT EXISTS idx_exercise_responses_learner_id ON exercise_responses(learner_id);
CREATE INDEX IF NOT EXISTS idx_comprehension_responses_lesson_id ON comprehension_responses(lesson_id);
CREATE INDEX IF NOT EXISTS idx_comprehension_responses_learner_id ON comprehension_responses(learner_id);
CREATE INDEX IF NOT EXISTS idx_learner_mastery_learner_id ON learner_mastery(learner_id);
CREATE INDEX IF NOT EXISTS idx_learner_mastery_concept_id ON learner_mastery(concept_id);
CREATE INDEX IF NOT EXISTS idx_generation_runs_lesson_id ON generation_runs(lesson_id);
CREATE INDEX IF NOT EXISTS idx_generation_runs_task_type ON generation_runs(task_type);
CREATE INDEX IF NOT EXISTS idx_pilot_evidence_learner_id ON pilot_evidence(learner_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_lesson_id ON idempotency_keys(lesson_id);