-- #8130: external events and daily summaries share the existing outbox.
-- Add nullable columns only; existing rows and receipts stay unchanged.
ALTER TABLE ops_alert_outbox ADD COLUMN notify_site TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_audience TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_kind TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_title TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_source_id TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_day TEXT;
ALTER TABLE ops_alert_outbox ADD COLUMN notify_count INTEGER;
