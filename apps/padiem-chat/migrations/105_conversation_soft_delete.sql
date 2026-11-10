-- #7388: conversation deletion becomes a marker with a 30-day retention
-- window, so the row leaves every product surface immediately while an
-- operator can still restore it server-side inside the window.
--
-- NULL means "live". A non-NULL value is the UTC ISO timestamp (`…Z`, the same
-- fixed-width format `purge_expired_rows` compares lexicographically) at which
-- the owner deleted the conversation. The row keeps its messages and its R2
-- originals until `app.conversation_purge` removes all three together.
--
-- The partial index is the purge pass's own scan: only marked rows are in it,
-- so the live list/search/detail reads keep their existing plan.
--
-- No restore column and no second flag: a restore is the operator script
-- `ops/restore_conversation.sh` clearing this column, and a browser API never
-- exposes it.

ALTER TABLE conversations
    ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_deleted_at
    ON conversations(deleted_at)
    WHERE deleted_at IS NOT NULL;
