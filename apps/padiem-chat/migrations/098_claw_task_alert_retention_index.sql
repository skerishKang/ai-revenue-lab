-- Global retention selection is by kind/status and then created_at. The older
-- inbox indexes begin with workspace_id and cannot serve this bounded purge.
CREATE INDEX IF NOT EXISTS idx_claw_task_alert_retention
    ON claw_task_alert (kind, status, created_at);
