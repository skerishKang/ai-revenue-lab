-- B64 provider reward events (issue #987, ayeT server-to-server connection).
--
-- The provider contract already existed as pure functions
-- (`ayet-s2s-postback.ts`, `reward-events.ts`) with nothing to write to. This
-- table is the missing persistence, and it is ADDITIVE: `b64_user_income`,
-- `b64_member`, `b64_session` and `b64_member_google` keep their rows and their
-- columns, and no statement here touches them.
--
-- Identity of a row is the provider's own transaction key, not a B64 id:
-- `PRIMARY KEY (provider_id, provider_transaction_id)` is what makes a retried
-- postback land on the same row instead of crediting twice, which is the rule
-- ayeT states for `{transaction_id}`. `member_id` is resolved from the signed
-- B64 subject the provider echoes back, so a postback can never be aimed at a
-- member the event was not issued for.
--
-- A row records what the provider reported. It is not a wallet, not a balance
-- and not a payout: `state` reaching CONFIRMED never moves money, and the
-- income pipeline still counts only its own `PAID` records.
--
-- D1/SQLite dialect. Replay-safe: every statement is IF NOT EXISTS.
-- Applied ONLY by the dispatch-only B64 D1 provision gate; application code
-- never executes this DDL at runtime.

CREATE TABLE IF NOT EXISTS b64_reward_event (
  provider_id TEXT NOT NULL,
  provider_transaction_id TEXT NOT NULL,
  member_id TEXT NOT NULL,
  external_subject TEXT NOT NULL,
  amount REAL NOT NULL,
  unit TEXT NOT NULL,
  state TEXT NOT NULL,
  provider_verified INTEGER NOT NULL,
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  confirmed_at TEXT,
  reversed_at TEXT,
  PRIMARY KEY (provider_id, provider_transaction_id)
);

-- One member's own reward history. Scoped by member id, so a read for one
-- member cannot return another member's row.
CREATE INDEX IF NOT EXISTS idx_b64_reward_event_member ON b64_reward_event (member_id);
