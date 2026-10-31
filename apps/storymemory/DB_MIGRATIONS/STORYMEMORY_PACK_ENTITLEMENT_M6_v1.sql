-- StoryMemory SM-091 / Marketplace M6
-- Paid Entitlement + Settlement Boundary
-- LLM-first / Source-grounded / DB-on-demand: monetary durable state only.

CREATE TABLE IF NOT EXISTS storymemory.pack_offers (
  offer_id text PRIMARY KEY,
  pack_id text NOT NULL REFERENCES storymemory.pack_registry(pack_id) ON DELETE CASCADE,
  version text NULL,
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  amount_minor bigint NOT NULL CHECK (amount_minor > 0),
  offer_status text NOT NULL DEFAULT 'active' CHECK (offer_status IN ('active','inactive')),
  access_scope text NOT NULL DEFAULT 'pack' CHECK (access_scope IN ('pack','version')),
  license jsonb NOT NULL DEFAULT '{}'::jsonb,
  refund_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','card_number','cardNumber','cvv','cvc','bank_account','bankAccount','raw_payload','rawPayload'])),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pack_offers_pack_version_fk FOREIGN KEY (pack_id, version) REFERENCES storymemory.pack_versions(pack_id, version) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS pack_offers_pack_status_idx ON storymemory.pack_offers(pack_id, offer_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_purchase_transactions (
  purchase_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text NOT NULL,
  pack_id text NOT NULL REFERENCES storymemory.pack_registry(pack_id) ON DELETE RESTRICT,
  offer_id text NOT NULL REFERENCES storymemory.pack_offers(offer_id) ON DELETE RESTRICT,
  version text NULL,
  provider text NOT NULL,
  provider_transaction_id text NULL,
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  purchase_status text NOT NULL CHECK (purchase_status IN ('intent','pending','paid','failed','cancelled','refunded','chargeback')),
  receipt_reference text NULL,
  initiated_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','card_number','cardNumber','cvv','cvc'])),
  CONSTRAINT pack_purchase_pack_version_fk FOREIGN KEY (pack_id, version) REFERENCES storymemory.pack_versions(pack_id, version) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS pack_purchase_provider_tx_unique ON storymemory.pack_purchase_transactions(provider, provider_transaction_id) WHERE provider_transaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS pack_purchase_user_idx ON storymemory.pack_purchase_transactions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS pack_purchase_pack_idx ON storymemory.pack_purchase_transactions(pack_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_payment_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_id uuid NOT NULL REFERENCES storymemory.pack_purchase_transactions(purchase_id) ON DELETE CASCADE,
  provider text NOT NULL,
  provider_event_id text NOT NULL,
  event_type text NOT NULL,
  verified boolean NOT NULL DEFAULT false,
  occurred_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  payload_digest text NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','card_number','cardNumber','cvv','cvc','raw_payload','rawPayload']))
);

CREATE UNIQUE INDEX IF NOT EXISTS pack_payment_provider_event_unique ON storymemory.pack_payment_events(provider, provider_event_id);
CREATE INDEX IF NOT EXISTS pack_payment_purchase_idx ON storymemory.pack_payment_events(purchase_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_entitlements (
  entitlement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text NOT NULL,
  pack_id text NOT NULL REFERENCES storymemory.pack_registry(pack_id) ON DELETE RESTRICT,
  version text NULL,
  access_scope text NOT NULL DEFAULT 'pack' CHECK (access_scope IN ('pack','version')),
  entitlement_status text NOT NULL CHECK (entitlement_status IN ('active','revoked','refunded','chargeback','expired')),
  source_purchase_id uuid NULL REFERENCES storymemory.pack_purchase_transactions(purchase_id) ON DELETE RESTRICT,
  starts_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NULL,
  revoked_at timestamptz NULL,
  reason text NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','card_number','cardNumber','cvv','cvc','bank_account','bankAccount','raw_payload','rawPayload'])),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pack_entitlement_pack_version_fk FOREIGN KEY (pack_id, version) REFERENCES storymemory.pack_versions(pack_id, version) ON DELETE RESTRICT,
  CONSTRAINT pack_entitlement_expiry_order CHECK (expires_at IS NULL OR expires_at > starts_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS pack_entitlement_user_pack_unique ON storymemory.pack_entitlements(user_id, pack_id);
CREATE INDEX IF NOT EXISTS pack_entitlement_user_status_idx ON storymemory.pack_entitlements(user_id, entitlement_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_settlement_entries (
  settlement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_id uuid NOT NULL UNIQUE REFERENCES storymemory.pack_purchase_transactions(purchase_id) ON DELETE RESTRICT,
  pack_id text NOT NULL REFERENCES storymemory.pack_registry(pack_id) ON DELETE RESTRICT,
  creator_id text NOT NULL,
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  gross_minor bigint NOT NULL CHECK (gross_minor >= 0),
  platform_fee_minor bigint NOT NULL CHECK (platform_fee_minor >= 0),
  creator_net_minor bigint NOT NULL CHECK (creator_net_minor >= 0),
  settlement_status text NOT NULL CHECK (settlement_status IN ('pending','eligible','held','paid','reversed')),
  payout_reference text NULL,
  eligible_at timestamptz NULL,
  paid_at timestamptz NULL,
  reversed_at timestamptz NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','bank_account','bankAccount','card_number','cardNumber'])),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pack_settlement_arithmetic CHECK (gross_minor = platform_fee_minor + creator_net_minor),
  CONSTRAINT pack_settlement_paid_reference CHECK (settlement_status <> 'paid' OR (payout_reference IS NOT NULL AND length(trim(payout_reference)) > 0))
);

CREATE INDEX IF NOT EXISTS pack_settlement_creator_status_idx ON storymemory.pack_settlement_entries(creator_id, settlement_status, updated_at DESC);

ALTER TABLE storymemory.pack_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_purchase_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_payment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_settlement_entries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pack_offers_read_visible ON storymemory.pack_offers;
CREATE POLICY pack_offers_read_visible ON storymemory.pack_offers FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM storymemory.pack_registry r WHERE r.pack_id = pack_offers.pack_id AND ((r.publication_status='published' AND r.visibility='public') OR r.creator_id=(SELECT auth.user_id()))));

DROP POLICY IF EXISTS pack_purchase_read_own ON storymemory.pack_purchase_transactions;
CREATE POLICY pack_purchase_read_own ON storymemory.pack_purchase_transactions FOR SELECT TO authenticated
USING (user_id = (SELECT auth.user_id()));

DROP POLICY IF EXISTS pack_payment_events_read_own ON storymemory.pack_payment_events;
CREATE POLICY pack_payment_events_read_own ON storymemory.pack_payment_events FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM storymemory.pack_purchase_transactions p WHERE p.purchase_id=pack_payment_events.purchase_id AND p.user_id=(SELECT auth.user_id())));

DROP POLICY IF EXISTS pack_entitlements_read_own ON storymemory.pack_entitlements;
CREATE POLICY pack_entitlements_read_own ON storymemory.pack_entitlements FOR SELECT TO authenticated
USING (user_id = (SELECT auth.user_id()));

DROP POLICY IF EXISTS pack_settlement_creator_read ON storymemory.pack_settlement_entries;
CREATE POLICY pack_settlement_creator_read ON storymemory.pack_settlement_entries FOR SELECT TO authenticated
USING (creator_id = (SELECT auth.user_id()));

REVOKE ALL ON storymemory.pack_offers FROM authenticated;
REVOKE ALL ON storymemory.pack_purchase_transactions FROM authenticated;
REVOKE ALL ON storymemory.pack_payment_events FROM authenticated;
REVOKE ALL ON storymemory.pack_entitlements FROM authenticated;
REVOKE ALL ON storymemory.pack_settlement_entries FROM authenticated;
GRANT SELECT ON storymemory.pack_offers TO authenticated;
GRANT SELECT ON storymemory.pack_purchase_transactions TO authenticated;
GRANT SELECT ON storymemory.pack_payment_events TO authenticated;
GRANT SELECT ON storymemory.pack_entitlements TO authenticated;
GRANT SELECT ON storymemory.pack_settlement_entries TO authenticated;

CREATE OR REPLACE VIEW storymemory.pack_entitlement_access WITH (security_invoker=true) AS
SELECT entitlement_id,user_id,pack_id,version,access_scope,entitlement_status,starts_at,expires_at,revoked_at,source_purchase_id,reason,metadata,updated_at,
       (entitlement_status='active' AND starts_at<=now() AND (expires_at IS NULL OR expires_at>now())) AS access_active
FROM storymemory.pack_entitlements;

CREATE OR REPLACE VIEW storymemory.pack_settlement_summary WITH (security_invoker=true) AS
SELECT creator_id,currency,settlement_status,count(*) AS entry_count,sum(gross_minor) AS gross_minor,sum(platform_fee_minor) AS platform_fee_minor,sum(creator_net_minor) AS creator_net_minor
FROM storymemory.pack_settlement_entries
GROUP BY creator_id,currency,settlement_status;

GRANT SELECT ON storymemory.pack_entitlement_access TO authenticated;
GRANT SELECT ON storymemory.pack_settlement_summary TO authenticated;
