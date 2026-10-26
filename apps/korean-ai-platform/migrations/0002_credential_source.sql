-- PR-3a (#5824): whose credential paid for the call.
--
-- b14_model_call already says what B14 selected and how the call ended, but it
-- cannot say whether the platform's own Provider key was spent or a key the
-- caller supplied for this one request. Those are different acts: one is
-- platform consumption, the other is the customer spending their own account.
-- The dashboard has to be able to tell them apart without reading a request
-- body, so the distinction is stored as a category.
--
-- The column holds one of two labels and nothing else. No key, no endpoint and
-- no provider account identity is recorded here; the provider that answered is
-- already carried by selected_provider, and a call row that says 'user' means
-- only that the credential came from the request.
--
-- Existing rows take the default. Application code never mutates this schema at
-- request time; the D1 provision gate and the local runtime's migration list are
-- the only paths that apply this file, and both record the name so an ALTER that
-- is not replay-safe runs exactly once.

ALTER TABLE b14_model_call ADD COLUMN credential_source TEXT NOT NULL DEFAULT 'pool'
  CHECK (credential_source IN ('pool','user'));
