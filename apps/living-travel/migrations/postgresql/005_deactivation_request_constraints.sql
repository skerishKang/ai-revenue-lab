-- Enforce one pending deactivation request per traveler (PostgreSQL).
-- Uses ctid (PostgreSQL physical row id) in place of SQLite rowid.

UPDATE deactivation_requests
SET status = 'cancelled',
    updated_at = to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
WHERE status = 'pending'
  AND ctid NOT IN (
      SELECT MIN(ctid)
      FROM deactivation_requests
      WHERE status = 'pending'
      GROUP BY traveler_id
  );

CREATE UNIQUE INDEX IF NOT EXISTS ux_deactivation_requests_one_pending
ON deactivation_requests (traveler_id)
WHERE status = 'pending';
