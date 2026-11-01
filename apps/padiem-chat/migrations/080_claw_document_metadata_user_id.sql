-- #6323: add owner column; 080a backfills only rows with proven owners.
ALTER TABLE claw_document_metadata ADD COLUMN user_id TEXT;
