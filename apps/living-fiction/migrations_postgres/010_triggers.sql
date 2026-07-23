-- Reader-deletion privacy trigger.
--
-- When a reader transitions to 'deleted', rewrite the idempotency keys of their
-- branch-generation requests to an anonymized form so the original
-- request-identity link can no longer be reconstructed. Mirrors the SQLite
-- trigger trg_reader_delete_anonymize_branch_request_keys.
--
-- The random suffix uses gen_random_uuid() (built into PostgreSQL 13+, no
-- extension required); the dashes are stripped to yield 32 lowercase hex chars,
-- matching the SQLite lower(hex(randomblob(16))) suffix. The prefix test uses
-- left() rather than LIKE to keep the statement free of '%' tokens.

CREATE OR REPLACE FUNCTION trg_reader_delete_anonymize_branch_request_keys_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE branch_generation_requests
    SET idempotency_key =
        'anon-idem-' || replace(gen_random_uuid()::text, '-', '') || '-' || id
    WHERE reader_id = OLD.id
      AND left(idempotency_key, 10) <> 'anon-idem-';
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reader_delete_anonymize_branch_request_keys ON readers;

CREATE TRIGGER trg_reader_delete_anonymize_branch_request_keys
AFTER UPDATE OF status ON readers
FOR EACH ROW
WHEN (NEW.status = 'deleted' AND OLD.status <> 'deleted')
EXECUTE FUNCTION trg_reader_delete_anonymize_branch_request_keys_fn();
