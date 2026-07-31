-- Migration 004: Integrity constraints and indexes

-- 1. Prevent more than one non-failed lesson for a given learner, concept, and lesson_number
CREATE UNIQUE INDEX idx_lessons_active ON lessons (learner_id, concept_id, lesson_number) WHERE generation_status != 'generation_failed';

-- 2. Ensure request_id is unique across generation_runs when it is not empty
CREATE UNIQUE INDEX idx_gen_runs_req_id ON generation_runs (request_id) WHERE request_id != '';

-- 3. Useful indexes for exact feedback/lesson lookup
CREATE INDEX idx_feedback_lesson_learner ON feedback (lesson_id, learner_id);
CREATE INDEX idx_comprehension_lesson_learner ON comprehension_responses (lesson_id, learner_id);
