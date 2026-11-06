-- Preserve the provider's HTTP status on each failed or successful attempt.
ALTER TABLE b14_model_call_attempt ADD COLUMN http_status INTEGER
  CHECK (http_status IS NULL OR (http_status >= 100 AND http_status <= 599));
