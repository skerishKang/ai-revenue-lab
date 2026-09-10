-- DURABLE PERSISTENCE for #2057 ClawFollowupTask / ClawAlert contracts (#2328).
--
-- Additive only. Runtime CREATE TABLE is forbidden; migrations apply this
-- file. Does NOT reuse #2318 claw_run_history (owner-scoped, run-oriented).
--
-- Shared bounded table, workspace-owned, owner-scoped. A `kind` discriminator
-- ('task' | 'alert') distinguishes rows; `kind_value` holds the alert-specific
-- ClawAlertKind for alerts (NULL for tasks) to avoid overloading a column with
-- two different enum value-spaces. No secret / raw-body / raw-prompt / OAuth /
-- cookie columns are stored here.
CREATE TABLE IF NOT EXISTS claw_task_alert (
    id TEXT PRIMARY KEY,          -- stable task_id / alert_id
    workspace_id TEXT NOT NULL,
    kind TEXT NOT NULL,           -- 'task' | 'alert'
    status TEXT NOT NULL,         -- ClawTaskStatus.value | ClawAlertStatus.value
    title TEXT NOT NULL,          -- bounded by app layer (<=256)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    member_id TEXT NOT NULL DEFAULT '',  -- task: owner; alert: ''=all OR member
    due_date TEXT,                -- task only
    source_id TEXT,               -- task only
    linked_ref TEXT,              -- task only
    severity TEXT,                -- alert only
    kind_value TEXT,              -- alert only: ClawAlertKind.value
    visible_to_all INTEGER NOT NULL DEFAULT 1,  -- alert only
    CHECK (kind IN ('task','alert')),
    CHECK (status IN ('open','done','cancelled','active','dismissed')),
    CHECK (member_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_claw_task_alert_workspace_created
    ON claw_task_alert (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claw_task_alert_workspace_kind_status
    ON claw_task_alert (workspace_id, kind, status);
CREATE INDEX IF NOT EXISTS idx_claw_task_alert_member_updated
    ON claw_task_alert (member_id, updated_at DESC)
    WHERE member_id != '' AND kind = 'alert';

-- Bounded inbox window, enforced at query time via LIMIT in the adapter.
