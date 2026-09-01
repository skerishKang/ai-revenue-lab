-- P01 Engine durable idempotency store contract.
--
-- This migration is intentionally source-only in #1235. It documents the
-- repository-owned table shape required by CloudflareD1IdempotencyAdapter but
-- does not provision, bind, or deploy any Production D1 database.
-- Runtime code must not execute this DDL.

CREATE TABLE IF NOT EXISTS padiem_engine_idempotency (
  app_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('reserved', 'completed', 'aborted')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (app_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_idempotency_expires_at
  ON padiem_engine_idempotency (expires_at);

CREATE INDEX IF NOT EXISTS idx_padiem_engine_idempotency_state
  ON padiem_engine_idempotency (state);
