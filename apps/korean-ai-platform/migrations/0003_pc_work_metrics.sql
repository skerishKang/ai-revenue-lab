-- #6460: final Engine-observed PC turn counters annotate one existing B14 call.
-- No prompt, path, file content or credential is stored. Model usage/cost rows
-- keep their existing meaning; this is not a new billing or execution record.
ALTER TABLE b14_model_call ADD COLUMN pc_work_metrics_json TEXT;
ALTER TABLE b14_model_call ADD COLUMN pc_work_metrics_recorded_at TEXT;

CREATE INDEX IF NOT EXISTS b14_model_call_pc_turn
ON b14_model_call (product, subject_ref, session_ref);
