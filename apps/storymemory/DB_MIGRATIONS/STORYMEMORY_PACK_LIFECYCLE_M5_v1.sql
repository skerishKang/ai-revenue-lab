-- SM-090 Pack Version / Rating / Fork Lifecycle (Marketplace M5)
-- Durable Marketplace metadata only. No Source body / knowledge precompute.

create table if not exists storymemory.pack_version_proposals (
  id uuid primary key default gen_random_uuid(),
  pack_id text not null references storymemory.pack_registry(pack_id) on delete cascade,
  proposed_version text not null,
  parent_version text not null,
  proposer_id text not null,
  artifact_uri text not null,
  artifact_fingerprint text not null,
  schema_version text not null default 'storymemory-precision-pack-1.0',
  declared_trust_tier text not null default 'auto-generated' check (declared_trust_tier in ('auto-generated','community-reviewed','curated','expert','official')),
  source_match_mode text not null default 'exact-fingerprint' check (source_match_mode in ('exact-fingerprint','source-id','work-revision')),
  compatibility jsonb not null default '{}'::jsonb,
  rights jsonb not null default '{}'::jsonb,
  changelog text not null,
  proposal_status text not null default 'draft' check (proposal_status in ('draft','pending_review','approved','rejected','withdrawn')),
  review_note text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(pack_id, proposed_version),
  check (coalesce((rights->>'sourceTextIncluded')::boolean,false)=false)
);

create table if not exists storymemory.pack_ratings (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  pack_id text not null,
  version text not null,
  overall_rating smallint not null check (overall_rating between 1 and 5),
  accuracy_rating smallint check (accuracy_rating between 1 and 5),
  explanation_rating smallint check (explanation_rating between 1 and 5),
  citation_rating smallint check (citation_rating between 1 and 5),
  spoiler_safety_rating smallint check (spoiler_safety_rating between 1 and 5),
  speed_cost_rating smallint check (speed_cost_rating between 1 and 5),
  review_text text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key(pack_id,version) references storymemory.pack_versions(pack_id,version) on delete cascade,
  unique(user_id, pack_id, version)
);

create table if not exists storymemory.pack_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  pack_id text not null,
  version text not null,
  feedback_kind text not null check (feedback_kind in ('error','correction','compatibility','rights','other')),
  source_locator text,
  message text not null,
  proposed_correction jsonb not null default '{}'::jsonb,
  feedback_status text not null default 'open' check (feedback_status in ('open','reviewed','accepted','rejected','closed')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key(pack_id,version) references storymemory.pack_versions(pack_id,version) on delete cascade,
  constraint pack_feedback_locator_required_check check (feedback_kind not in ('error','correction','compatibility') or nullif(btrim(source_locator),'') is not null),
  constraint pack_feedback_no_source_body_keys_check check (not (proposed_correction ?| array['sourceText','source_text','sourceBody','source_body','fullText','full_text','rawSource','raw_source']))
);

create index if not exists pack_version_proposals_review_idx on storymemory.pack_version_proposals(pack_id,proposal_status,updated_at desc);
create index if not exists pack_ratings_pack_version_idx on storymemory.pack_ratings(pack_id,version,updated_at desc);
create index if not exists pack_feedback_pack_version_idx on storymemory.pack_feedback(pack_id,version,feedback_status,updated_at desc);

alter table storymemory.pack_version_proposals enable row level security;
alter table storymemory.pack_ratings enable row level security;
alter table storymemory.pack_feedback enable row level security;

drop policy if exists pack_version_proposals_own_read on storymemory.pack_version_proposals;
create policy pack_version_proposals_own_read on storymemory.pack_version_proposals for select to authenticated
  using (proposer_id=(select auth.user_id()));
drop policy if exists pack_version_proposals_creator_insert on storymemory.pack_version_proposals;
create policy pack_version_proposals_creator_insert on storymemory.pack_version_proposals for insert to authenticated
  with check (proposer_id=(select auth.user_id()) and proposal_status='draft' and exists (
    select 1 from storymemory.pack_registry r where r.pack_id=pack_version_proposals.pack_id and r.creator_id=(select auth.user_id())
  ));
drop policy if exists pack_version_proposals_creator_update on storymemory.pack_version_proposals;
create policy pack_version_proposals_creator_update on storymemory.pack_version_proposals for update to authenticated
  using (proposer_id=(select auth.user_id()) and proposal_status='draft')
  with check (proposer_id=(select auth.user_id()) and proposal_status in ('draft','pending_review','withdrawn'));
drop policy if exists pack_version_proposals_creator_delete on storymemory.pack_version_proposals;
create policy pack_version_proposals_creator_delete on storymemory.pack_version_proposals for delete to authenticated
  using (proposer_id=(select auth.user_id()) and proposal_status in ('draft','withdrawn'));

drop policy if exists pack_ratings_own on storymemory.pack_ratings;
create policy pack_ratings_own on storymemory.pack_ratings for all to authenticated
  using (user_id=(select auth.user_id()))
  with check (user_id=(select auth.user_id()) and exists (
    select 1 from storymemory.pack_registry r where r.pack_id=pack_ratings.pack_id and r.publication_status='published' and r.visibility='public'
  ));

drop policy if exists pack_feedback_own on storymemory.pack_feedback;
create policy pack_feedback_own on storymemory.pack_feedback for all to authenticated
  using (user_id=(select auth.user_id()))
  with check (user_id=(select auth.user_id()) and exists (
    select 1 from storymemory.pack_registry r where r.pack_id=pack_feedback.pack_id and ((r.publication_status='published' and r.visibility='public') or r.creator_id=(select auth.user_id()))
  ));

grant select,insert,update,delete on storymemory.pack_version_proposals to authenticated;
grant select,insert,update,delete on storymemory.pack_ratings to authenticated;
grant select,insert,update,delete on storymemory.pack_feedback to authenticated;

-- Aggregated public ratings expose no user_id/review text.
create or replace view storymemory.pack_rating_summary as
select r.pack_id, r.version,
       count(*)::bigint as rating_count,
       round(avg(r.overall_rating)::numeric,2) as overall_average,
       round(avg(r.accuracy_rating)::numeric,2) as accuracy_average,
       round(avg(r.explanation_rating)::numeric,2) as explanation_average,
       round(avg(r.citation_rating)::numeric,2) as citation_average,
       round(avg(r.spoiler_safety_rating)::numeric,2) as spoiler_safety_average,
       round(avg(r.speed_cost_rating)::numeric,2) as speed_cost_average,
       max(r.updated_at) as last_rating_at
from storymemory.pack_ratings r
join storymemory.pack_registry p on p.pack_id=r.pack_id
where p.publication_status='published' and p.visibility='public'
group by r.pack_id,r.version;
grant select on storymemory.pack_rating_summary to authenticated;
