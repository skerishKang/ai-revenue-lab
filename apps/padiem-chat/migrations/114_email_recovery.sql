-- Mail-proven restoration of a Chat-only withdrawal (#7606). Token preimages
-- never enter either ledger. A target has no users row until redemption, so
-- user_id deliberately has no foreign key; account deletion removes its rows.
CREATE TABLE IF NOT EXISTS password_recovery_tokens (
    token_digest TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    account_id TEXT NOT NULL,
    credential_epoch TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at INTEGER,
    consumed_by TEXT UNIQUE,
    CHECK (expires_at = issued_at + 900),
    CHECK ((consumed_at IS NULL) = (consumed_by IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_password_recovery_tokens_user ON password_recovery_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_recovery_tokens_expiry ON password_recovery_tokens(expires_at);
-- Keep cleanup atomic even when foreign keys are disabled. Older code can
-- still delete users, and disabled recovery needs no new table-dependent SQL.
CREATE TRIGGER IF NOT EXISTS password_recovery_tokens_user_delete
BEFORE DELETE ON users
BEGIN
    DELETE FROM password_recovery_tokens
    WHERE user_id = OLD.id
       OR (consumed_at IS NULL AND lower(email) = lower(OLD.email));
END;

-- The shared login supplies an opaque, domain-separated HMAC of the source
-- address. Chat hashes the email independently. No raw address is retained.
CREATE TABLE IF NOT EXISTS password_recovery_requests (
    request_id TEXT PRIMARY KEY,
    identifier_digest TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    issued_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_recovery_requests_identifier
    ON password_recovery_requests(identifier_digest, issued_at);
CREATE INDEX IF NOT EXISTS idx_password_recovery_requests_source
    ON password_recovery_requests(source_digest, issued_at);
CREATE INDEX IF NOT EXISTS idx_password_recovery_requests_time
    ON password_recovery_requests(issued_at);
