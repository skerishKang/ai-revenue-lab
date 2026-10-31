-- #5034 Web Push subscriptions for the EXISTING user web-alert inbox.
--
-- Additive only. This table stores no notification record: the inbox records
-- stay in the existing claw_task_alert authority (#2057/#2328). It stores only
-- the browser device endpoint that a user explicitly opted in, the keys the
-- browser generated for that endpoint, and the origin scope the subscription
-- is allowed to notify for.
--
-- Ownership is server-derived: workspace_id + member_id come from the signed
-- session, never from the request body. One device endpoint is one row per
-- account: re-subscribing the same endpoint updates the row instead of
-- creating a duplicate.
--
-- No raw user content, no prompt, no OAuth, no cookie, and no API key is
-- stored here. The endpoint is a device capability URL and is never echoed
-- back to a browser or written to a log.
CREATE TABLE IF NOT EXISTS claw_push_subscription (
    id TEXT PRIMARY KEY,              -- stable subscription id (endpoint digest)
    workspace_id TEXT NOT NULL,
    member_id TEXT NOT NULL,          -- the signed-in owner this device belongs to
    endpoint TEXT NOT NULL,           -- browser push endpoint (device capability URL)
    p256dh TEXT NOT NULL,            -- browser-generated client public key
    auth TEXT NOT NULL,               -- browser-generated client auth secret
    scope TEXT NOT NULL,              -- origin scope this subscription may notify for
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, member_id, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_claw_push_subscription_owner
    ON claw_push_subscription (workspace_id, member_id, updated_at DESC);
