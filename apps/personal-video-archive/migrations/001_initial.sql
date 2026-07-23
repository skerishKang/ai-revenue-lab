-- Phase 1 migration: core schema for Personal Video Archive.
-- All tables are workspace-local.  No shared code or root changes.

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    intent TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_rules (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    primary_query TEXT NOT NULL,
    related_queries TEXT NOT NULL DEFAULT '[]',
    required_terms TEXT NOT NULL DEFAULT '[]',
    excluded_terms TEXT NOT NULL DEFAULT '[]',
    preferred_languages TEXT NOT NULL DEFAULT '[]',
    included_channels TEXT NOT NULL DEFAULT '[]',
    excluded_channels TEXT NOT NULL DEFAULT '[]',
    duration_preference TEXT NOT NULL DEFAULT 'any',
    shorts_preference TEXT NOT NULL DEFAULT 'include',
    date_window_start TEXT,
    date_window_end TEXT,
    default_sort TEXT NOT NULL DEFAULT 'newest',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_video_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    channel_id TEXT NOT NULL DEFAULT '',
    channel_title TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    duration_seconds INTEGER,
    view_count INTEGER,
    like_count INTEGER,
    thumbnail_url TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL DEFAULT 'youtube',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, provider_video_id)
);

CREATE TABLE IF NOT EXISTS topic_videos (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    first_matched_at TEXT NOT NULL,
    last_matched_at TEXT NOT NULL,
    match_score REAL CHECK(match_score IS NULL OR (match_score >= 0 AND match_score <= 1)),
    match_reasons TEXT NOT NULL DEFAULT '[]',
    is_excluded INTEGER NOT NULL DEFAULT 0 CHECK(is_excluded IN (0, 1)),
    provenance TEXT NOT NULL DEFAULT 'application',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(topic_id, video_id)
);

CREATE TABLE IF NOT EXISTS timestamp_references (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES viewing_records(id) ON DELETE CASCADE,
    timestamp_seconds INTEGER NOT NULL CHECK(timestamp_seconds >= 0),
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS viewing_records (
    id TEXT PRIMARY KEY,
    topic_video_id TEXT NOT NULL REFERENCES topic_videos(id) ON DELETE CASCADE,
    viewing_state TEXT NOT NULL DEFAULT 'unseen',
    rating INTEGER CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
    reflection TEXT NOT NULL DEFAULT '',
    learned_point TEXT NOT NULL DEFAULT '',
    agreement TEXT NOT NULL DEFAULT '',
    disagreement TEXT NOT NULL DEFAULT '',
    uncertainty TEXT NOT NULL DEFAULT '',
    follow_up_plan TEXT NOT NULL DEFAULT '',
    free_form_note TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    opened_date TEXT,
    completed_date TEXT,
    provenance TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    videos_found INTEGER NOT NULL DEFAULT 0 CHECK(videos_found >= 0),
    videos_added INTEGER NOT NULL DEFAULT 0 CHECK(videos_added >= 0),
    videos_updated INTEGER NOT NULL DEFAULT 0 CHECK(videos_updated >= 0),
    quota_cost INTEGER NOT NULL DEFAULT 0 CHECK(quota_cost >= 0),
    error_message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    sync_run_id TEXT REFERENCES sync_runs(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    cost INTEGER NOT NULL CHECK(cost >= 0),
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    topic_id TEXT REFERENCES topics(id) ON DELETE SET NULL,
    record_id TEXT REFERENCES viewing_records(id) ON DELETE SET NULL,
    proposal_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_text TEXT NOT NULL DEFAULT '',
    proposed_json TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'valid',
    validation_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_videos_topic ON topic_videos(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_videos_video ON topic_videos(video_id);
CREATE INDEX IF NOT EXISTS idx_viewing_records_state ON viewing_records(viewing_state);
CREATE INDEX IF NOT EXISTS idx_sync_runs_topic ON sync_runs(topic_id);
CREATE INDEX IF NOT EXISTS idx_quota_ledger_topic ON quota_ledger(topic_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
