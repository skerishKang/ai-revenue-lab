-- #7543 S02/S05/S06/S10: share the "drop this cache" signal between worker
-- processes.
--
-- Four short-lived caches live in worker memory on purpose (the identity reads,
-- the Claw connector scope, the connector-tool grant decision and the
-- subject→account mapping). Making the values themselves shared would mean
-- serialising response objects; the invalidations are few and rare, so only the
-- signal is shared: one integer per cache scope here, the values stay in each
-- worker's memory next to the number they were stored under.
--
-- A process that invalidates adds one to the scope's number. A process that
-- reads adds nothing and, at most once per request, compares the number it
-- read with the one stored beside its entry. A different number (or a row that
-- arrived after the entry) means the entry is dropped and the authority is
-- asked again. Scope names are fixed strings owned by the app; no user id,
-- subject, session or credential value is ever written here, and the table is
-- never read on a path that can refuse a request, so a missing or unreadable
-- row can only mean "keep today's behaviour".
CREATE TABLE IF NOT EXISTS worker_cache_generation (
  scope TEXT NOT NULL PRIMARY KEY CHECK (length(scope) BETWEEN 1 AND 64),
  generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
  updated_at_ms INTEGER NOT NULL
);

-- The five scopes exist from the first boot, so a worker that caches before any
-- invalidation still stored a number a later bump can be compared with. A value
-- of 0 means "nobody has invalidated this scope yet".
INSERT OR IGNORE INTO worker_cache_generation (scope, generation, updated_at_ms) VALUES
  ('identity_auth_session', 0, 0),
  ('identity_owner_scope', 0, 0),
  ('identity_subject_mapping', 0, 0),
  ('pc_connector_scope', 0, 0),
  ('connector_tool_grant', 0, 0);
