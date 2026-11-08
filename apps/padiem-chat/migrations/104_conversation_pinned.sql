-- #7175: per-owner conversation pin for the sidebar "상단 고정" group.
--
-- One owner's recent conversations can be pinned so they stay above the
-- recency ordering on every device. The pin is a server-owned boolean: the
-- browser never stores it, and a signed-in read on another device returns it.
--
-- TOLERANCE (#7147): existing reads must keep working before this migration is
-- applied. The store therefore tries the pinned projection first and, on
-- "no such column: pinned", re-runs the same owner/product-scoped read without
-- it and reports pinned=false. A missing column means "nothing is pinned yet",
-- never a failed conversation list.
--
-- ORDERING: pinned first, then recency. The index matches the list query's
-- (user_id, product_scope) bound with the same sort direction.
--
-- DEFAULT 0 keeps a legacy insert path from creating an unpinned-looking NULL
-- row; the column is NOT NULL so the projection is always a boolean.

ALTER TABLE conversations
    ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_conversations_user_product_pinned_updated
    ON conversations(user_id, product_scope, pinned DESC, updated_at DESC);
