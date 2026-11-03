-- #6695 PR-2 — the presence receipt records the owner accounts it is for.
--
-- `mesh_device_presence` kept only connectivity facts (device, connected,
-- receipt time, generation, source). The owner accounts were resolved on the
-- way in (`_record_mesh_presence` asks the pairing directory, falling back to
-- the deployment map) and then dropped, so every reader had to re-derive
-- ownership at read time. The row now carries the account list the directory
-- answered with, so a later lookup can scope by owner from the row itself.
-- Additive only: NULL keeps an existing row exactly as it was.
ALTER TABLE mesh_device_presence ADD COLUMN account_refs_json TEXT;
