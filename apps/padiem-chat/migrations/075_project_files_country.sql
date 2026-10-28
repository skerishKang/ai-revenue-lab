-- #6046: content country for the 의원3종 documents.
-- Every existing row is Korean work, so the default is 'kr' and no row is
-- rewritten, renamed or backfilled. The value selects output language and
-- wording only — it is not a jurisdiction or a storage-region decision.
-- SQLite's ALTER TABLE ADD COLUMN cannot carry a CHECK, so the four allowed
-- values are enforced at the API boundary (request_contract.COUNTRIES).
ALTER TABLE project_files ADD COLUMN country TEXT NOT NULL DEFAULT 'kr';
