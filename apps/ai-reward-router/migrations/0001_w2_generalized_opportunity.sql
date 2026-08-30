BEGIN;

CREATE TABLE sources (
  source_id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  lane TEXT NOT NULL,
  launch_priority TEXT NOT NULL,
  country_scope TEXT NOT NULL,
  access_mode TEXT NOT NULL,
  login_required BOOLEAN NOT NULL,
  js_rendered TEXT NOT NULL,
  monetization_role TEXT NOT NULL,
  verification_state TEXT NOT NULL,
  risk_tier TEXT NOT NULL,
  update_cadence TEXT NOT NULL,
  official_base_url TEXT NULL,
  list_url TEXT NULL,
  next_action TEXT NULL,
  notes TEXT NULL,
  acquisition_mode TEXT NOT NULL,
  opportunity_class_hint JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_endpoints (
  endpoint_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  endpoint_kind TEXT NOT NULL,
  url TEXT NULL,
  requires_auth TEXT NOT NULL,
  render_mode TEXT NOT NULL,
  intended_behavior TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  evidence_notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_policy_reviews (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  robots_status TEXT NOT NULL,
  terms_status TEXT NOT NULL,
  commercial_reuse TEXT NOT NULL,
  text_reuse TEXT NOT NULL,
  image_logo_reuse TEXT NOT NULL,
  automation_permission TEXT NOT NULL,
  affiliate_incentive TEXT NOT NULL,
  policy_evidence_url TEXT NULL,
  reviewed_at TIMESTAMPTZ NULL,
  reviewer TEXT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('PENDING','PASS','PASS_WITH_LIMITS','BLOCK')),
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_collection_gates (
  gate_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  gate TEXT NOT NULL,
  required BOOLEAN NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('NOT_STARTED','IN_PROGRESS','PASS','FAIL','WAIVED')),
  failure_action TEXT NOT NULL CHECK (failure_action IN ('BLOCK','SHADOW')),
  evidence TEXT NULL,
  notes TEXT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, gate_id)
);

CREATE TABLE source_snapshots (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  endpoint_id TEXT NULL REFERENCES source_endpoints(endpoint_id),
  acquired_at TIMESTAMPTZ NOT NULL,
  acquisition_mode_used TEXT NOT NULL,
  canonical_url TEXT NULL,
  content_type TEXT NULL,
  raw_location TEXT NULL,
  raw_payload JSONB NULL,
  content_hash TEXT NOT NULL,
  fetch_metadata JSONB NULL,
  actor_provenance JSONB NULL,
  http_status INTEGER NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (raw_location IS NOT NULL OR raw_payload IS NOT NULL)
);
CREATE UNIQUE INDEX source_snapshots_dedup_idx
  ON source_snapshots (source_id, COALESCE(canonical_url, ''), content_hash);
CREATE INDEX source_snapshots_source_acquired_idx ON source_snapshots (source_id, acquired_at DESC);

CREATE TABLE merchants (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  canonical_domain TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE offers (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  merchant_id TEXT NULL REFERENCES merchants(id),
  canonical_key TEXT NOT NULL,
  provider_external_key TEXT NULL,
  lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('DISCOVERED','PARSED','REVIEW_REQUIRED','VERIFIED','LIVE','EXPIRING','ENDED','STALE','ARCHIVED','REJECTED')),
  current_version_id TEXT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, canonical_key)
);
CREATE INDEX offers_state_seen_idx ON offers (lifecycle_state, last_seen_at DESC);

CREATE TABLE offer_versions (
  id TEXT PRIMARY KEY,
  offer_id TEXT NOT NULL REFERENCES offers(id),
  version_number INTEGER NOT NULL CHECK (version_number > 0),
  source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
  title TEXT NOT NULL,
  short_summary TEXT NULL,
  original_language TEXT NULL,
  verification_state TEXT NOT NULL CHECK (verification_state IN ('UNVERIFIED','REVIEW_REQUIRED','VERIFIED','REJECTED')),
  source_snapshot_hash TEXT NOT NULL,
  model_id TEXT NULL,
  prompt_version TEXT NULL,
  input_hash TEXT NULL,
  opportunity_category TEXT NOT NULL CHECK (opportunity_category IN ('REWARDED_AD','OFFERWALL','SURVEY','MARKET_RESEARCH','USER_TESTING','AI_EVALUATION','DATA_ANNOTATION','DATA_REVIEW','TRANSLATION','TRANSCRIPTION','CONTENT_MODERATION','SEARCH_OR_QUALITY_EVALUATION','MICROTASK','AFFILIATE_ACTION','CASHBACK','PROMOTION','REMOTE_FREELANCE','REMOTE_PROJECT','RECURRING_DIGITAL_WORK','OTHER_VERIFIED_ONLINE_INCOME')),
  income_ladder_level TEXT NOT NULL CHECK (income_ladder_level IN ('MICRO_REWARD','TASK_WORK','SKILLED_DIGITAL_GIG','PROJECT_WORK','RECURRING_SIDE_JOB')),
  compensation_type TEXT NOT NULL CHECK (compensation_type IN ('FIXED','HOURLY','PER_TASK','PER_UNIT','VARIABLE','COMMISSION','BENEFIT','DRAW','OTHER')),
  advertised_compensation_value NUMERIC NULL,
  expected_payout_value NUMERIC NULL,
  compensation_currency TEXT NULL,
  estimated_active_minutes NUMERIC NULL,
  estimated_total_effort_minutes NUMERIC NULL,
  application_minutes NUMERIC NULL,
  qualification_screening_minutes NUMERIC NULL,
  preparation_minutes NUMERIC NULL,
  start_latency_minutes NUMERIC NULL,
  payout_method JSONB NULL,
  payout_delay JSONB NULL,
  provider_fees JSONB NULL,
  repeatability JSONB NULL,
  supply_availability_state TEXT NULL,
  supply_observed_at TIMESTAMPTZ NULL,
  application_required BOOLEAN NULL,
  qualification_required BOOLEAN NULL,
  qualification_probability NUMERIC NULL,
  acceptance_probability NUMERIC NULL,
  rejection_or_reversal_risk JSONB NULL,
  payout_reliability JSONB NULL,
  eligible_countries_or_regions JSONB NULL,
  language_requirements JSONB NULL,
  skill_requirements JSONB NULL,
  device_os_requirements JSONB NULL,
  identity_kyc_requirements JSONB NULL,
  age_requirements JSONB NULL,
  tax_contractor_requirements JSONB NULL,
  scheduling_requirements JSONB NULL,
  canonical_destination_url TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (offer_id, version_number),
  CHECK (advertised_compensation_value IS NULL OR advertised_compensation_value >= 0),
  CHECK (expected_payout_value IS NULL OR expected_payout_value >= 0),
  CHECK (estimated_active_minutes IS NULL OR estimated_active_minutes >= 0),
  CHECK (estimated_total_effort_minutes IS NULL OR estimated_total_effort_minutes >= 0),
  CHECK (application_minutes IS NULL OR application_minutes >= 0),
  CHECK (qualification_screening_minutes IS NULL OR qualification_screening_minutes >= 0),
  CHECK (preparation_minutes IS NULL OR preparation_minutes >= 0),
  CHECK (start_latency_minutes IS NULL OR start_latency_minutes >= 0),
  CHECK (qualification_probability IS NULL OR (qualification_probability >= 0 AND qualification_probability <= 1)),
  CHECK (acceptance_probability IS NULL OR (acceptance_probability >= 0 AND acceptance_probability <= 1))
);
CREATE INDEX offer_versions_offer_version_idx ON offer_versions (offer_id, version_number DESC);
CREATE INDEX offer_versions_verification_created_idx ON offer_versions (verification_state, created_at DESC);

ALTER TABLE offers
  ADD CONSTRAINT offers_current_version_fk FOREIGN KEY (current_version_id) REFERENCES offer_versions(id);

CREATE TABLE offer_evidence (
  id TEXT PRIMARY KEY,
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
  field_path TEXT NOT NULL,
  evidence_text TEXT NULL,
  evidence_locator JSONB NULL,
  evidence_hash TEXT NOT NULL,
  confidence NUMERIC NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE offer_requirements (
  id TEXT PRIMARY KEY,
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  requirement_type TEXT NOT NULL CHECK (requirement_type IN ('LANGUAGE','SKILL','QUALIFICATION','IDENTITY_KYC','AGE','SCHEDULE','COUNTRY_REGION','PAYMENT_METHOD','TAX_CONTRACTOR','OTHER')),
  operator TEXT NOT NULL,
  normalized_value JSONB NULL,
  display_text TEXT NOT NULL,
  required BOOLEAN NOT NULL,
  confidence NUMERIC NULL,
  evidence_id TEXT NULL REFERENCES offer_evidence(id),
  CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE offer_compensation_components (
  id TEXT PRIMARY KEY,
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  component_type TEXT NOT NULL CHECK (component_type IN ('FIXED_PAY','HOURLY_RATE','PER_TASK','PER_UNIT','BONUS','CASHBACK','POINT','DISCOUNT','COUPON','PRIZE','BENEFIT','COMMISSION','OTHER')),
  amount NUMERIC NULL,
  currency TEXT NULL,
  rate_unit TEXT NULL,
  percent NUMERIC NULL,
  cap_amount NUMERIC NULL,
  condition_text TEXT NULL,
  evidence_id TEXT NULL REFERENCES offer_evidence(id),
  CHECK (amount IS NULL OR amount >= 0),
  CHECK (percent IS NULL OR percent >= 0),
  CHECK (cap_amount IS NULL OR cap_amount >= 0)
);

CREATE TABLE offer_windows (
  id TEXT PRIMARY KEY,
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  window_type TEXT NOT NULL CHECK (window_type IN ('PARTICIPATION','APPLICATION','SCREENING','QUALIFICATION','WORK','SUBMISSION','REVIEW','PURCHASE','DRAW','PAYOUT','CLAIM')),
  start_at TIMESTAMPTZ NULL,
  end_at TIMESTAMPTZ NULL,
  relative_rule TEXT NULL,
  display_text TEXT NOT NULL,
  evidence_id TEXT NULL REFERENCES offer_evidence(id),
  CHECK (start_at IS NULL OR end_at IS NULL OR end_at >= start_at)
);
CREATE INDEX offer_windows_type_end_idx ON offer_windows (window_type, end_at);

CREATE TABLE offer_changes (
  id TEXT PRIMARY KEY,
  offer_id TEXT NOT NULL REFERENCES offers(id),
  previous_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  new_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  material BOOLEAN NOT NULL,
  change_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE review_queue (
  id TEXT PRIMARY KEY,
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  reason_codes JSONB NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('LOW','NORMAL','HIGH','CRITICAL')),
  state TEXT NOT NULL CHECK (state IN ('OPEN','IN_REVIEW','RESOLVED')),
  assigned_to TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ NULL
);
CREATE INDEX review_queue_state_priority_idx ON review_queue (state, priority, created_at);

CREATE TABLE review_decisions (
  id TEXT PRIMARY KEY,
  review_queue_id TEXT NOT NULL REFERENCES review_queue(id),
  offer_version_id TEXT NOT NULL REFERENCES offer_versions(id),
  decision TEXT NOT NULL CHECK (decision IN ('APPROVE','MODIFY_APPROVE','REJECT')),
  reviewer_id TEXT NOT NULL,
  approval_reason TEXT NULL,
  rejection_reason TEXT NULL,
  patch JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
