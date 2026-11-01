-- StoryMemory SM-092 / Marketplace M7
-- Expert / Official Verification + Attestation Program
-- Trust metadata only. No Source body, no per-Source knowledge precompute.

CREATE TABLE IF NOT EXISTS storymemory.pack_verifiers (
  verifier_id text PRIMARY KEY,
  display_name text NOT NULL,
  verifier_kind text NOT NULL CHECK (verifier_kind IN ('expert','publisher','author','institution')),
  verifier_status text NOT NULL DEFAULT 'pending' CHECK (verifier_status IN ('pending','active','suspended','revoked')),
  organization_name text NULL,
  profile_reference text NULL,
  authority_scope jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (authority_scope ?| ARRAY['source_text','sourceText','body','content','full_text','fullText'])),
  verified_identity_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pack_verifiers_status_kind_idx ON storymemory.pack_verifiers(verifier_status,verifier_kind,updated_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_verifier_credentials (
  credential_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  verifier_id text NOT NULL REFERENCES storymemory.pack_verifiers(verifier_id) ON DELETE RESTRICT,
  credential_type text NOT NULL,
  issuer_name text NOT NULL,
  credential_reference text NOT NULL,
  credential_fingerprint text NOT NULL,
  credential_status text NOT NULL DEFAULT 'pending' CHECK (credential_status IN ('pending','active','expired','revoked')),
  valid_from timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  authority_scope jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (authority_scope ?| ARRAY['source_text','sourceText','body','content','full_text','fullText'])),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText','id_number','idNumber','license_image','licenseImage','raw_document','rawDocument'])),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pack_verifier_credential_validity CHECK (valid_until > valid_from),
  CONSTRAINT pack_verifier_credential_unique UNIQUE (verifier_id,credential_fingerprint)
);
CREATE INDEX IF NOT EXISTS pack_verifier_credentials_status_idx ON storymemory.pack_verifier_credentials(verifier_id,credential_status,valid_until DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_verification_requests (
  request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pack_id text NOT NULL,
  version text NOT NULL,
  requester_id text NOT NULL,
  requested_tier text NOT NULL CHECK (requested_tier IN ('expert','official')),
  source_fingerprint text NOT NULL CHECK (length(trim(source_fingerprint)) > 0),
  verification_scope jsonb NOT NULL CHECK (verification_scope <> '{}'::jsonb AND NOT (verification_scope ?| ARRAY['source_text','sourceText','body','content','full_text','fullText'])),
  request_status text NOT NULL DEFAULT 'submitted' CHECK (request_status IN ('submitted','in_review','approved','rejected','withdrawn')),
  assigned_verifier_id text NULL REFERENCES storymemory.pack_verifiers(verifier_id) ON DELETE RESTRICT,
  review_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (review_summary ?| ARRAY['source_text','sourceText','body','content','full_text','fullText'])),
  reviewed_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pack_verification_request_version_fk FOREIGN KEY (pack_id,version) REFERENCES storymemory.pack_versions(pack_id,version) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS pack_verification_requests_pack_idx ON storymemory.pack_verification_requests(pack_id,version,request_status,updated_at DESC);
CREATE INDEX IF NOT EXISTS pack_verification_requests_requester_idx ON storymemory.pack_verification_requests(requester_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS storymemory.pack_attestation_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attestation_id uuid NOT NULL REFERENCES storymemory.pack_attestations(id) ON DELETE CASCADE,
  event_type text NOT NULL CHECK (event_type IN ('issued','revalidated','revoked','expired')),
  actor_verifier_id text NULL,
  event_at timestamptz NOT NULL DEFAULT now(),
  reason text NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (metadata ?| ARRAY['source_text','sourceText','body','content','full_text','fullText']))
);
CREATE INDEX IF NOT EXISTS pack_attestation_events_att_idx ON storymemory.pack_attestation_events(attestation_id,event_at DESC);

ALTER TABLE storymemory.pack_attestations ADD COLUMN IF NOT EXISTS credential_id uuid NULL REFERENCES storymemory.pack_verifier_credentials(credential_id) ON DELETE RESTRICT;
ALTER TABLE storymemory.pack_attestations ADD COLUMN IF NOT EXISTS request_id uuid NULL REFERENCES storymemory.pack_verification_requests(request_id) ON DELETE RESTRICT;
ALTER TABLE storymemory.pack_attestations DROP CONSTRAINT IF EXISTS pack_attestations_verifier_kind_check;
ALTER TABLE storymemory.pack_attestations ADD CONSTRAINT pack_attestations_verifier_kind_check CHECK (verifier_kind IN ('host','registry','expert','publisher','author','institution'));
ALTER TABLE storymemory.pack_attestations DROP CONSTRAINT IF EXISTS pack_attestations_program_scope_check;
ALTER TABLE storymemory.pack_attestations ADD CONSTRAINT pack_attestations_program_scope_check CHECK (tier NOT IN ('expert','official') OR (source_fingerprint IS NOT NULL AND length(trim(source_fingerprint))>0 AND verification_scope <> '{}'::jsonb AND expires_at IS NOT NULL AND expires_at > issued_at AND credential_id IS NOT NULL AND request_id IS NOT NULL));

CREATE OR REPLACE FUNCTION storymemory.enforce_pack_attestation_program() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v storymemory.pack_verifiers%ROWTYPE; c storymemory.pack_verifier_credentials%ROWTYPE; r storymemory.pack_verification_requests%ROWTYPE;
BEGIN
  IF NEW.tier NOT IN ('expert','official') THEN RETURN NEW; END IF;
  SELECT * INTO v FROM storymemory.pack_verifiers WHERE verifier_id=NEW.verifier_id;
  IF NOT FOUND OR v.verifier_status <> 'active' OR v.verifier_kind <> NEW.verifier_kind THEN RAISE EXCEPTION 'PACK_VERIFIER_NOT_ACTIVE_OR_KIND_MISMATCH'; END IF;
  SELECT * INTO c FROM storymemory.pack_verifier_credentials WHERE credential_id=NEW.credential_id;
  IF NOT FOUND OR c.verifier_id<>NEW.verifier_id OR c.credential_status<>'active' OR c.valid_from>NEW.issued_at OR c.valid_until<=NEW.issued_at THEN RAISE EXCEPTION 'PACK_VERIFIER_CREDENTIAL_INVALID'; END IF;
  IF NOT ((c.authority_scope->'tiers') ? NEW.tier) THEN RAISE EXCEPTION 'PACK_VERIFIER_CREDENTIAL_TIER_SCOPE_MISMATCH'; END IF;
  SELECT * INTO r FROM storymemory.pack_verification_requests WHERE request_id=NEW.request_id;
  IF NOT FOUND OR r.request_status<>'approved' OR r.pack_id<>NEW.pack_id OR r.version<>NEW.version OR r.requested_tier<>NEW.tier OR r.source_fingerprint<>NEW.source_fingerprint OR r.assigned_verifier_id IS DISTINCT FROM NEW.verifier_id OR NOT (r.verification_scope @> NEW.verification_scope) THEN RAISE EXCEPTION 'PACK_VERIFICATION_REQUEST_NOT_APPROVED_OR_SCOPE_MISMATCH'; END IF;
  IF NEW.tier='official' AND NEW.verifier_kind NOT IN ('publisher','author','institution') THEN RAISE EXCEPTION 'PACK_OFFICIAL_VERIFIER_KIND_INVALID'; END IF;
  IF NEW.tier='expert' AND NEW.verifier_kind NOT IN ('expert','publisher','author','institution') THEN RAISE EXCEPTION 'PACK_EXPERT_VERIFIER_KIND_INVALID'; END IF;
  IF NEW.status='valid' AND NEW.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'PACK_ATTESTATION_VALID_CANNOT_BE_REVOKED'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS pack_attestation_program_guard ON storymemory.pack_attestations;
CREATE TRIGGER pack_attestation_program_guard BEFORE INSERT OR UPDATE ON storymemory.pack_attestations FOR EACH ROW EXECUTE FUNCTION storymemory.enforce_pack_attestation_program();

CREATE OR REPLACE FUNCTION storymemory.audit_pack_attestation_program() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE evt text;
BEGIN
  IF TG_OP='INSERT' THEN evt='issued';
  ELSIF NEW.status='revoked' AND OLD.status IS DISTINCT FROM NEW.status THEN evt='revoked';
  ELSIF NEW.status='expired' AND OLD.status IS DISTINCT FROM NEW.status THEN evt='expired';
  ELSIF NEW.expires_at IS DISTINCT FROM OLD.expires_at OR NEW.verification_scope IS DISTINCT FROM OLD.verification_scope THEN evt='revalidated';
  ELSE RETURN NEW; END IF;
  INSERT INTO storymemory.pack_attestation_events(attestation_id,event_type,actor_verifier_id,reason,metadata) VALUES(NEW.id,evt,NEW.verifier_id,NULL,'{}'::jsonb);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS pack_attestation_program_audit ON storymemory.pack_attestations;
CREATE TRIGGER pack_attestation_program_audit AFTER INSERT OR UPDATE ON storymemory.pack_attestations FOR EACH ROW EXECUTE FUNCTION storymemory.audit_pack_attestation_program();

ALTER TABLE storymemory.pack_verifiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_verifier_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_verification_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE storymemory.pack_attestation_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pack_verification_requests_own_read ON storymemory.pack_verification_requests;
CREATE POLICY pack_verification_requests_own_read ON storymemory.pack_verification_requests FOR SELECT TO authenticated USING (requester_id=(SELECT auth.user_id()) OR EXISTS (SELECT 1 FROM storymemory.pack_registry p WHERE p.pack_id=pack_verification_requests.pack_id AND p.creator_id=(SELECT auth.user_id())));
DROP POLICY IF EXISTS pack_verification_requests_own_insert ON storymemory.pack_verification_requests;
CREATE POLICY pack_verification_requests_own_insert ON storymemory.pack_verification_requests FOR INSERT TO authenticated WITH CHECK (requester_id=(SELECT auth.user_id()) AND request_status='submitted' AND assigned_verifier_id IS NULL AND EXISTS (SELECT 1 FROM storymemory.pack_registry p WHERE p.pack_id=pack_verification_requests.pack_id AND p.creator_id=(SELECT auth.user_id())));
DROP POLICY IF EXISTS pack_attestation_events_visible ON storymemory.pack_attestation_events;
CREATE POLICY pack_attestation_events_visible ON storymemory.pack_attestation_events FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM storymemory.pack_attestations a JOIN storymemory.pack_registry p ON p.pack_id=a.pack_id WHERE a.id=pack_attestation_events.attestation_id AND ((p.publication_status='published' AND p.visibility='public') OR p.creator_id=(SELECT auth.user_id()))));

REVOKE ALL ON storymemory.pack_verifiers FROM authenticated;
REVOKE ALL ON storymemory.pack_verifier_credentials FROM authenticated;
REVOKE ALL ON storymemory.pack_verification_requests FROM authenticated;
REVOKE ALL ON storymemory.pack_attestation_events FROM authenticated;
GRANT SELECT,INSERT ON storymemory.pack_verification_requests TO authenticated;
GRANT SELECT ON storymemory.pack_attestation_events TO authenticated;

CREATE OR REPLACE VIEW storymemory.pack_verification_public_state AS
SELECT a.id AS attestation_id,a.pack_id,a.version,a.tier,a.source_fingerprint,a.verification_scope,a.status AS attestation_status,a.issued_at,a.expires_at,a.revoked_at,
       v.verifier_id,v.display_name AS verifier_display_name,v.verifier_kind,v.verifier_status,v.organization_name AS verifier_organization,
       c.credential_id,c.credential_type,c.issuer_name AS credential_issuer,c.credential_status,c.valid_from AS credential_valid_from,c.valid_until AS credential_valid_until,c.authority_scope AS credential_authority_scope,
       r.request_id,r.request_status,pv.artifact_fingerprint
FROM storymemory.pack_attestations a
JOIN storymemory.pack_verifiers v ON v.verifier_id=a.verifier_id
JOIN storymemory.pack_verifier_credentials c ON c.credential_id=a.credential_id AND c.verifier_id=a.verifier_id
JOIN storymemory.pack_verification_requests r ON r.request_id=a.request_id
JOIN storymemory.pack_versions pv ON pv.pack_id=a.pack_id AND pv.version=a.version
JOIN storymemory.pack_registry pr ON pr.pack_id=a.pack_id
WHERE a.tier IN ('expert','official') AND pr.publication_status='published' AND pr.visibility='public';
GRANT SELECT ON storymemory.pack_verification_public_state TO authenticated;
