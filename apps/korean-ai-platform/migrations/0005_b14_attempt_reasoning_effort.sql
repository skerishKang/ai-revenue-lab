-- #6838: the reasoning level B14 actually sent for this physical attempt.
-- NULL means the attempt carried no reasoning option at all (an unsupported
-- model, or a provider that rejected the option and was retried without it).
ALTER TABLE b14_model_call_attempt ADD COLUMN reasoning_effort TEXT;
