-- #4672 / #4316: one paid B66 model turn claim across Cloudflare Worker isolates.
-- SOURCE ONLY: protected D1 apply and readback require a separate release gate.
-- Ordered after 041 quote state, 042 product history scope, 043 Claw grant.
-- This is a B66 dispatch receipt, NOT an entitlement or durable quote authoring.
-- No auto-expiry/reclaim: a provider timeout has uncertain billing outcome.
-- No customer text, request JSON, credentials or provider response in this table.
CREATE TABLE IF NOT EXISTS b66_ai_turn_attempt (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_scope TEXT NOT NULL CHECK (product_scope = 'b66-quote'),
    turn_token TEXT NOT NULL CHECK (length(turn_token) = 32),
    model_id TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    state TEXT NOT NULL CHECK (state IN ('claimed', 'completed')),
    conversation_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, product_scope, turn_token),
    CHECK (
        (state = 'claimed' AND conversation_id IS NULL)
        OR (state = 'completed' AND conversation_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_b66_attempt_owner_state
    ON b66_ai_turn_attempt (user_id, product_scope, state, created_at);
