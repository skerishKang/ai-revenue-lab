-- PADIEM Custom multi-provider BYOK: bind each owner/provider credential to
-- the effective API endpoint. Additive only; rows written before this
-- migration keep NULL and are read through the provider default endpoint
-- with the legacy AAD, then re-sealed on the next successful read.
-- Application order: after 053. No existing column or row is rewritten here.
PRAGMA foreign_keys = ON;

ALTER TABLE chat_custom_provider_credentials ADD COLUMN endpoint TEXT;
