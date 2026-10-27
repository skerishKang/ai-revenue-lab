-- LoveTree 4.0 sign-in handoff — one-time, server-side login evidence (#5977 follow-up).
--
-- LoveTree keeps its own front door and its own session cookie, but it is not an
-- identity authority. The existing PADIEM login is the only component that can say
-- "this Google identity was verified in this browser for this login request". This
-- table is how that statement crosses the boundary exactly once.
--
-- Shape reused from `058_android_auth_handoff.sql` (the Android 1.0.1 sign-in return
-- contract): one row per login request, only digests of the caller-facing state, the
-- verified identity written by the login side, and every transition expressed as a
-- single conditional UPDATE so a late, replayed, or expired request cannot advance a
-- row. This is not a second account authority: `pending_user_id` is the existing
-- `users.id` produced by the existing Google upsert, and the row never carries a
-- session token. Session issuance happens on the identity authority, in the
-- `lovetree-auth-caller` relay, and only after this row has been claimed.
--
-- Bindings, in the order they are enforced:
--   product_id + recipient  — which product and which relay may claim this row
--   state_sha256            — which LoveTree login request it belongs to (claim must present it)
--   return_origin           — where the finished login may send the browser, fixed at creation
--   expires_at              — how long it stays alive (the relay re-checks it)
--   status                  — single use: 'ready' -> 'claimed' happens at most once

CREATE TABLE IF NOT EXISTS lovetree_login_handoffs (
    ticket_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL CHECK (product_id = 'lovetree-4-0'),
    recipient TEXT NOT NULL CHECK (recipient = 'lovetree-auth-caller'),
    state_sha256 TEXT NOT NULL CHECK (length(state_sha256) = 64),
    return_origin TEXT NOT NULL CHECK (
        -- Origin only: https host (+ optional path-free), or loopback http for tests.
        -- A path, query, fragment, or userinfo would make the return leg an open redirect.
        (
            substr(return_origin, 1, 8) = 'https://'
            AND substr(return_origin, 9) NOT GLOB '*[/?#@ ]*'
            AND instr(substr(return_origin, 9), '.') > 0
        )
        OR (
            substr(return_origin, 1, 7) = 'http://'
            AND (substr(return_origin, 8) LIKE '127.0.0.1:%' OR substr(return_origin, 8) LIKE 'localhost:%')
        )
    ),
    status TEXT NOT NULL DEFAULT 'awaiting_login'
        CHECK (status IN ('awaiting_login', 'ready', 'claimed')),
    pending_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    auth_provider TEXT CHECK (auth_provider IN ('google', 'password')),
    provider_subject TEXT CHECK (length(provider_subject) BETWEEN 1 AND 255),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    bound_at TEXT,
    claimed_at TEXT,
    expires_at TEXT NOT NULL,
    -- A row is only 'ready' once the verified identity is written, and identity
    -- never exists on a row that has not been bound.
    CHECK (
        (status = 'awaiting_login' AND pending_user_id IS NULL AND auth_provider IS NULL AND provider_subject IS NULL)
        OR (status IN ('ready', 'claimed') AND pending_user_id IS NOT NULL AND auth_provider IS NOT NULL AND provider_subject IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_lovetree_login_handoffs_expires_at
    ON lovetree_login_handoffs (expires_at);
