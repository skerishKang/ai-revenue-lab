-- #6323 follow-up (a) of #2952: generated-document metadata carries its owner.
--
-- No backfill. The rows that exist before this migration are the 30-day set the
-- #6318 read-only count measured (30 rows, none unexpired on 2026-10-30), and
-- an unproven owner is not an owner. A NULL user_id is never readable: the read
-- path binds the requester's id, so a pre-migration row stays unreadable rather
-- than being attributed to whoever happens to ask first.
ALTER TABLE claw_document_metadata ADD COLUMN user_id TEXT;
