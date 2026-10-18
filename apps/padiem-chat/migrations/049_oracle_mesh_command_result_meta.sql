-- #5015 model-driven PC drive query: persist executor-observed outcome.
-- Additive only: two nullable columns, no table rebuild, no data rewrite.
-- The Engine lane re-feeds the exact termination/exit_code to the model
-- instead of inventing one; existing 047/048 rows keep NULL (unknown).
ALTER TABLE oracle_mesh_dispatch ADD COLUMN termination TEXT;
ALTER TABLE oracle_mesh_dispatch ADD COLUMN exit_code INTEGER;
