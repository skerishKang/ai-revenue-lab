-- #B14 attempt deadline: preserve why an upstream attempt timed out.
ALTER TABLE b14_model_call_attempt ADD COLUMN timeout_reason TEXT
  CHECK (timeout_reason IS NULL OR timeout_reason IN ('first_byte','attempt_total','chain_budget'));
