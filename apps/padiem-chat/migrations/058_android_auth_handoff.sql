-- B62 Android 1.0.1 sign-in return contract — one-time server-side handoff.
--
-- Android 1.0.0 opens the Google authorization URL in the device's external
-- browser. That browser never receives the WebView's OAuth state cookie and its
-- session cookie is never shared back into the WebView, so a login completed
-- there cannot become a WebView session by itself.
--
-- This table lets the WebView create a login request, the external browser
-- complete Google authentication and confirm a code shown in the app, and the
-- original WebView claim the result exactly once. It is not a second account
-- authority: `pending_user_id` is the existing `users.id` row produced by the
-- existing Google upsert, and the claim route issues the existing
-- `padiem_session` token. Only HMAC digests of the claim secret and the
-- user-visible confirmation code are stored.

CREATE TABLE IF NOT EXISTS padiem_android_auth_handoffs (
    handoff_id TEXT PRIMARY KEY,
    secret_hash TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_login'
        CHECK (status IN (
            'awaiting_login',
            'awaiting_confirmation',
            'ready',
            'claimed',
            'cancelled'
        )),
    pending_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    pending_at TEXT,
    confirmed_at TEXT,
    claimed_at TEXT,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_padiem_android_auth_handoffs_expires_at
    ON padiem_android_auth_handoffs (expires_at);
