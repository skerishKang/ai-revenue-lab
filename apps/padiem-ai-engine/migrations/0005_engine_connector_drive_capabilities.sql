-- #2222: add Drive capability grants to the existing connector-grant table.
-- Source migration only; applying it to any environment is a separate release action.
-- Existing Gmail rows remain valid because the new column defaults to an empty list.

ALTER TABLE padiem_engine_connector_grants
  ADD COLUMN granted_capabilities_json TEXT NOT NULL DEFAULT '[]';
