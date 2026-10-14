-- #4657: server-owned product discriminator for owner conversations.
--
-- ORDERING: apply AFTER 041_b66_ai_conversation.sql. 041 is LOCAL4's B66 quote
-- AI conversation state/revision table and is unrelated to this change; this
-- migration was renumbered from 041 to 042 so it does not collide with it. The
-- sequence is 040 -> 041 (LOCAL4) -> 042 (this file).
--
-- One account owns conversations for more than one PADIEM product. Owner
-- scoping alone was therefore not visibility scoping: every conversation query
-- filtered by `user_id` only, so a B66 request could list, read or delete the
-- same account's Chat/Claw dialogue through the generic routes, and Chat could
-- equally read B66 dialogue.
--
-- This adds the discriminator that the data-access boundary now enforces on
-- every list/search/detail/delete/append, in both directions.
--
-- Backfill: every conversation that already exists is Chat/Claw dialogue, so it
-- receives 'b62-chat'. That is what preserves existing Chat project semantics
-- and Claw historical continuity; no row changes owner or visibility.
--
-- The column is NOT NULL with a default so a legacy insert path cannot create an
-- unscoped row, and it is indexed together with the owner because every
-- conversation read is (user_id, product_scope) bounded.

ALTER TABLE conversations
    ADD COLUMN product_scope TEXT NOT NULL DEFAULT 'b62-chat';

CREATE INDEX IF NOT EXISTS idx_conversations_user_product_updated
    ON conversations(user_id, product_scope, updated_at DESC);
