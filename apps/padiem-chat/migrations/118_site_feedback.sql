-- Public site feedback (issue #7690). No account, no IP, no external delivery.
CREATE TABLE IF NOT EXISTS site_feedback (
    id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 2000),
    screen_json TEXT,
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','reviewing','fixed','deferred')),
    ops_memo TEXT,
    created_day TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS site_feedback_site_list
    ON site_feedback(site, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS site_feedback_status_list
    ON site_feedback(status, created_at DESC, id DESC);
-- Rate-limit hash only. The raw address is never written; rows older than one day are purged.
CREATE TABLE IF NOT EXISTS site_feedback_rate (
    rate_hash TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
    PRIMARY KEY(rate_hash, day)
);