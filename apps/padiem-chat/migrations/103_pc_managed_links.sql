-- 2026-11-08 representative decision: an administrator marks a managed
-- (contract) PC, and with user mode ON `mode="system"` runs only on
-- (administrator AND managed PC).
--
-- Additive only. `pc_device_links` holds one row per (account, PC) pair, so the
-- mark is per pair. `managed_by` names the administrator who set it; an unmark
-- clears both columns. Durable allow/deny evidence is the `padiem_mcp_audit`
-- row plus the `pc_link_managed` request event.
--
-- `padiem_mcp_audit.command_bytes` records only the UTF-8 length of the shell
-- command. The command body itself is never stored; exact material stays
-- correlated by `request_digest`.
ALTER TABLE pc_device_links ADD COLUMN managed_at TEXT;
ALTER TABLE pc_device_links ADD COLUMN managed_by TEXT;
ALTER TABLE padiem_mcp_audit ADD COLUMN command_bytes INTEGER;
