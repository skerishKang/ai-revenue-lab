-- Migration 013: Native Padiem Calendar durable persistence (#2834 Phase B-2).
--
-- Fully additive. No existing tables, columns, or indexes are modified.
-- Stores native work-logs and appointments for Padiem Calendar workspaces.
-- External calendar sync remains optional and out of scope.
--
-- Tables:
-- 1. padiem_calendar_work_log: daily work log entries (work-log != memory).
-- 2. padiem_calendar_appointment: date-only, all-day, and timed appointments.

CREATE TABLE IF NOT EXISTS padiem_calendar_work_log (
    id TEXT PRIMARY KEY,                       -- log_<hex>
    workspace_id TEXT NOT NULL,                -- workspace isolation key
    owner_id TEXT NOT NULL,                    -- owner user id
    date TEXT NOT NULL,                        -- YYYY-MM-DD
    title TEXT NOT NULL,                       -- bounded by app layer (<= 200 chars)
    content TEXT,                              -- bounded by app layer (<= 4000 chars)
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL                   -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_padiem_calendar_work_log_ws_date
    ON padiem_calendar_work_log (workspace_id, date, created_at);

CREATE INDEX IF NOT EXISTS idx_padiem_calendar_work_log_ws_owner
    ON padiem_calendar_work_log (workspace_id, owner_id);

CREATE TABLE IF NOT EXISTS padiem_calendar_appointment (
    id TEXT PRIMARY KEY,                       -- apt_<hex>
    workspace_id TEXT NOT NULL,                -- workspace isolation key
    owner_id TEXT NOT NULL,                    -- owner user id
    appointment_type TEXT NOT NULL,            -- 'date_only' | 'all_day' | 'timed'
    title TEXT NOT NULL,                       -- bounded by app layer (<= 200 chars)
    description TEXT,                          -- bounded by app layer (<= 4000 chars)
    date TEXT NOT NULL,                        -- YYYY-MM-DD
    start_at TEXT,                             -- ISO-8601 UTC for timed events
    end_at TEXT,                               -- ISO-8601 UTC for timed events
    timezone TEXT,                             -- explicit IANA timezone name
    reminder_minutes INTEGER,                  -- 0 to 40320
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL,                  -- ISO-8601 UTC
    CHECK (appointment_type IN ('date_only', 'all_day', 'timed')),
    CHECK (reminder_minutes IS NULL OR (reminder_minutes >= 0 AND reminder_minutes <= 40320))
);

CREATE INDEX IF NOT EXISTS idx_padiem_calendar_appointment_ws_date
    ON padiem_calendar_appointment (workspace_id, date, start_at);

CREATE INDEX IF NOT EXISTS idx_padiem_calendar_appointment_ws_owner
    ON padiem_calendar_appointment (workspace_id, owner_id);
