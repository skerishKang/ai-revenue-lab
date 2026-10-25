-- B64 user income pipeline durable storage (issue #987).
-- D1/SQLite dialect. Replay-safe: every statement is IF NOT EXISTS.
-- Applied ONLY by the dispatch-only B64 D1 provision gate
-- (.github/workflows/b64-d1-provision-gate.yml); application code never
-- executes this DDL at runtime.
-- Note: migrations/0001_w2_generalized_opportunity.sql is the product's
-- PostgreSQL persistence contract and is intentionally separate from this
-- D1/SQLite subtree (see migrations/README.md).

CREATE TABLE IF NOT EXISTS b64_user_income (
  id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  opportunity_id TEXT,
  external_ref TEXT,
  source_type TEXT NOT NULL
    CHECK (source_type IN ('AD_CLICK', 'PUBLIC_OPPORTUNITY', 'EXTERNAL_JOB', 'MANUAL')),
  title TEXT NOT NULL,
  vendor TEXT NOT NULL,
  status TEXT NOT NULL
    CHECK (status IN ('SAVED', 'APPLIED', 'IN_REVIEW', 'ACCEPTED', 'IN_PROGRESS',
                      'COMPLETED', 'PAID', 'REJECTED', 'EXPIRED', 'CANCELLED')),
  expected_amount REAL,
  expected_currency TEXT
    CHECK (expected_currency IS NULL OR expected_currency IN ('KRW', 'USD', 'EUR', 'GBP', 'JPY', 'OTHER')),
  actual_amount REAL,
  actual_currency TEXT
    CHECK (actual_currency IS NULL OR actual_currency IN ('KRW', 'USD', 'EUR', 'GBP', 'JPY', 'OTHER')),
  applied_at TEXT,
  accepted_at TEXT,
  completed_at TEXT,
  paid_at TEXT,
  expires_at TEXT,
  note TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, id)
);

CREATE INDEX IF NOT EXISTS idx_b64_user_income_user_updated
  ON b64_user_income (user_id, updated_at DESC);
