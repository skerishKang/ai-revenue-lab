-- SM-085 Pack Registry + Marketplace MVP
-- Metadata-only registry. No Source body / entity / relation / answer-card precompute.
create table if not exists storymemory.pack_registry (
  pack_id text primary key,
  name text not null,
  pack_type text not null check (pack_type in ('knowledge','harness','search','companion')),
  creator_id text not null,
  publisher_name text,
  summary text,
  visibility text not null default 'private' check (visibility in ('private','public','org')),
  pricing_mode text not null default 'free' check (pricing_mode in ('free','paid')),
  publication_status text not null default 'draft' check (publication_status in ('draft','pending_review','published','suspended')),
  latest_version text,
  source_text_included boolean not null default false,
  rights_declaration jsonb not null default '{}'::jsonb,
  compatibility_summary jsonb not null default '{}'::jsonb,
  permissions jsonb not null default '{}'::jsonb,
  processing_disclosure jsonb not null default '{}'::jsonb,
  listing_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (source_text_included = false),
  check ((visibility='private' and publication_status in ('draft','pending_review','suspended')) or visibility<>'private' or publication_status<>'published')
);
create table if not exists storymemory.pack_versions (
  pack_id text not null references storymemory.pack_registry(pack_id) on delete cascade,
  version text not null,
  schema_version text not null default 'storymemory-precision-pack-1.0',
  artifact_uri text not null,
  artifact_fingerprint text not null,
  declared_trust_tier text not null default 'auto-generated' check (declared_trust_tier in ('auto-generated','community-reviewed','curated','expert','official')),
  source_match_mode text not null default 'exact-fingerprint' check (source_match_mode in ('exact-fingerprint','source-id','work-revision')),
  compatibility jsonb not null default '{}'::jsonb,
  rights jsonb not null default '{}'::jsonb,
  changelog text,
  parent_version text,
  created_at timestamptz not null default now(),
  primary key(pack_id,version)
);
create table if not exists storymemory.pack_attestations (
  id uuid primary key default gen_random_uuid(), pack_id text not null, version text not null,
  verifier_id text not null, verifier_kind text not null check (verifier_kind in ('host','registry','expert','publisher','author')),
  tier text not null check (tier in ('community-reviewed','curated','expert','official')),
  verification_scope jsonb not null default '{}'::jsonb, source_fingerprint text,
  status text not null default 'valid' check (status in ('valid','revoked','expired')),
  issued_at timestamptz not null default now(), expires_at timestamptz, revoked_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  foreign key(pack_id,version) references storymemory.pack_versions(pack_id,version) on delete cascade
);
create table if not exists storymemory.pack_installs (
  id uuid primary key default gen_random_uuid(), user_id text not null, pack_id text not null, version text not null,
  source_identity text not null, source_fingerprint text, workspace_key text,
  install_status text not null default 'installed' check (install_status in ('installed','detached','disabled')),
  auto_update boolean not null default false, settings jsonb not null default '{}'::jsonb,
  attached_at timestamptz not null default now(), detached_at timestamptz, updated_at timestamptz not null default now(),
  foreign key(pack_id,version) references storymemory.pack_versions(pack_id,version) on delete restrict,
  unique(user_id,pack_id,source_identity)
);
create index if not exists pack_registry_discovery_idx on storymemory.pack_registry(publication_status,visibility,pricing_mode,pack_type,updated_at desc);
create index if not exists pack_versions_artifact_fingerprint_idx on storymemory.pack_versions(artifact_fingerprint);
create index if not exists pack_attestations_lookup_idx on storymemory.pack_attestations(pack_id,version,status,tier);
create index if not exists pack_installs_user_idx on storymemory.pack_installs(user_id,install_status,updated_at desc);
alter table storymemory.pack_registry enable row level security;
alter table storymemory.pack_versions enable row level security;
alter table storymemory.pack_attestations enable row level security;
alter table storymemory.pack_installs enable row level security;
-- Policies are included in the tested Main migration; see SM085 report/evidence for exact definitions.
create policy pack_registry_read_visible on storymemory.pack_registry for select to authenticated using (((publication_status='published' and visibility='public') or creator_id=(select auth.user_id())));
create policy pack_registry_creator_insert on storymemory.pack_registry for insert to authenticated with check (creator_id=(select auth.user_id()) and publication_status='draft' and visibility='private');
create policy pack_registry_creator_update on storymemory.pack_registry for update to authenticated using (creator_id=(select auth.user_id()) and publication_status in ('draft','pending_review')) with check (creator_id=(select auth.user_id()) and publication_status in ('draft','pending_review') and ((visibility='private' and publication_status='draft') or (visibility in ('public','org') and publication_status='pending_review')));
create policy pack_registry_creator_delete on storymemory.pack_registry for delete to authenticated using (creator_id=(select auth.user_id()) and publication_status in ('draft','pending_review'));
create policy pack_versions_read_visible on storymemory.pack_versions for select to authenticated using (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_versions.pack_id and ((r.publication_status='published' and r.visibility='public') or r.creator_id=(select auth.user_id()))));
create policy pack_versions_creator_insert on storymemory.pack_versions for insert to authenticated with check (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_versions.pack_id and r.creator_id=(select auth.user_id()) and r.publication_status in ('draft','pending_review')));
create policy pack_versions_creator_update on storymemory.pack_versions for update to authenticated using (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_versions.pack_id and r.creator_id=(select auth.user_id()) and r.publication_status in ('draft','pending_review'))) with check (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_versions.pack_id and r.creator_id=(select auth.user_id()) and r.publication_status in ('draft','pending_review')));
create policy pack_versions_creator_delete on storymemory.pack_versions for delete to authenticated using (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_versions.pack_id and r.creator_id=(select auth.user_id()) and r.publication_status in ('draft','pending_review')));
create policy pack_attestations_read_visible on storymemory.pack_attestations for select to authenticated using (exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_attestations.pack_id and ((r.publication_status='published' and r.visibility='public') or r.creator_id=(select auth.user_id()))));
create policy pack_installs_own on storymemory.pack_installs for all to authenticated using (user_id=(select auth.user_id())) with check (user_id=(select auth.user_id()) and exists (select 1 from storymemory.pack_registry r where r.pack_id=pack_installs.pack_id and ((r.publication_status='published' and r.visibility='public') or r.creator_id=(select auth.user_id()))));
grant select,insert,update,delete on storymemory.pack_registry to authenticated;
grant select,insert,update,delete on storymemory.pack_versions to authenticated;
grant select on storymemory.pack_attestations to authenticated;
grant select,insert,update,delete on storymemory.pack_installs to authenticated;
