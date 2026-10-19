-- #3580: owner-scoped canonical artifact delivery receipts (Telegram SEND).
--
-- Additive only, under the same Claw history persistence owner as the existing
-- run/artifact tables. This is NOT an approval authority, NOT a connector
-- authority and NOT a second artifact authority: it records only what an
-- already-authorized connector adapter reported for one delivery attempt, so
-- that (a) a repeated request can never deliver the same artifact twice and
-- (b) a failed attempt is never recorded as a success.
--
-- One row per (owner, conversation, workspace, artifact, artifact digest): the
-- UNIQUE key IS the duplicate-send guard. A row is reserved before the provider
-- call and completed after it; an unresolved reservation stays PENDING and
-- refuses a second attempt rather than re-sending.
--
-- A delivery that may have reached the provider is never retried from here: the
-- repository's existing rule is that recovery needs a separately authorized
-- reconciler, not a browser retry.

CREATE TABLE IF NOT EXISTS claw_artifact_delivery_receipts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    source_run_ref TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_integrity_ref TEXT NOT NULL,
    delivery_kind TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    delivery_intent_id TEXT NOT NULL,
    attempt_ref TEXT NOT NULL,
    receipt_ref TEXT,
    terminal_status TEXT NOT NULL,
    terminal_class TEXT NOT NULL,
    external_side_effect_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    external_result_ref TEXT,
    provider_error_ref TEXT,
    provider_error_kind TEXT,
    provider_error_retryable INTEGER,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, conversation_id, workspace_id, artifact_id, artifact_integrity_ref)
);

CREATE INDEX IF NOT EXISTS idx_claw_artifact_delivery_receipts_owner
ON claw_artifact_delivery_receipts (user_id, conversation_id, workspace_id, created_at DESC);
