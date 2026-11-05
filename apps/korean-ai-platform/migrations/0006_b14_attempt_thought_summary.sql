-- thought-summary stream: how many thinking-summary fragments this attempt
-- streamed in and their total character length. NULL means no thought request
-- rode the attempt (an unsupported model, or an endpoint that rejected the
-- option and was retried without it). The thought text itself is never
-- stored — the ledger answers "did thinking summaries arrive, and how much",
-- never "what did the model think".
ALTER TABLE b14_model_call_attempt ADD COLUMN thought_summary_count INTEGER;
ALTER TABLE b14_model_call_attempt ADD COLUMN thought_summary_chars INTEGER;
