-- Enforce one pending deactivation request per traveler.

UPDATE deactivation_requests
SET status = 'cancelled',
    updated_at = datetime('now')
WHERE status = 'pending'
  AND rowid NOT IN (
      SELECT MIN(rowid)
      FROM deactivation_requests
      WHERE status = 'pending'
      GROUP BY traveler_id
  );

CREATE UNIQUE INDEX IF NOT EXISTS ux_deactivation_requests_one_pending
ON deactivation_requests (traveler_id)
WHERE status = 'pending';
