-- #6724 MCP PC shell audit metadata.
--
-- The existing audit row keeps authentication and correlation identifiers plus
-- the request digest. A shell execution adds only closed numeric facts here:
-- the observed exit code, the wall-clock duration, the output size and whether
-- the returned output was truncated. The command text and the output itself
-- are deliberately absent; the log event carries the same numeric projection.
--
-- Additive only: existing audit rows keep NULL in these columns.
ALTER TABLE padiem_mcp_audit ADD COLUMN exit_code INTEGER;
ALTER TABLE padiem_mcp_audit ADD COLUMN duration_ms INTEGER;
ALTER TABLE padiem_mcp_audit ADD COLUMN output_bytes INTEGER;
ALTER TABLE padiem_mcp_audit ADD COLUMN output_truncated INTEGER;
