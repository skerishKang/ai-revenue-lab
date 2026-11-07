-- 대표 결정(2026-11-07): the Claw inbox (작업함) is removed. The Task/Alert
-- records lived in this table only, and production holds 0 rows, so the drop
-- carries no data migration. The automation results now live in the
-- automation's own conversation (one rule, one conversation) and the push
-- subscription rows stay in claw_push_subscription (untouched here).
DROP TABLE IF EXISTS claw_task_alert;
DROP INDEX IF EXISTS idx_claw_task_alert_workspace_created;
DROP INDEX IF EXISTS idx_claw_task_alert_workspace_kind_status;
DROP INDEX IF EXISTS idx_claw_task_alert_member_updated;
DROP INDEX IF EXISTS idx_claw_task_alert_retention;
