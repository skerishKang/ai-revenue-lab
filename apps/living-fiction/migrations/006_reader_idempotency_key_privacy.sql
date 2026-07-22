-- Migration 006: remove durable reader linkage from branch idempotency keys.
--
-- Default personal-branch idempotency keys include reader_id and reader_choice_id.
-- Reader deletion must therefore rotate the opaque key itself, not only the
-- structured reader_id / reader_choice_id columns.

-- Backfill databases where deletion occurred before this migration existed.
UPDATE branch_generation_requests
SET idempotency_key = 'anon-idem-' || lower(hex(randomblob(16))) || '-' || id
WHERE reader_id IN (
    SELECT id FROM readers WHERE status = 'deleted'
)
AND idempotency_key NOT LIKE 'anon-idem-%';

-- Enforce the same contract for every future reader status transition,
-- including callers that bypass the high-level deletion service.
DROP TRIGGER IF EXISTS trg_reader_delete_anonymize_branch_request_keys;
CREATE TRIGGER trg_reader_delete_anonymize_branch_request_keys
AFTER UPDATE OF status ON readers
WHEN NEW.status = 'deleted' AND OLD.status <> 'deleted'
BEGIN
    UPDATE branch_generation_requests
    SET idempotency_key = 'anon-idem-' || lower(hex(randomblob(16))) || '-' || id
    WHERE reader_id = OLD.id
      AND idempotency_key NOT LIKE 'anon-idem-%';
END;

PRAGMA user_version = 6;
