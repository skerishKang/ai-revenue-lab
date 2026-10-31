-- B66 #3180 ③ — one saved-quote asset table, two kinds of asset.
--
-- An owner who fills their own PC Excel form once can register that form as
-- "내 견적서". The record reuses this existing table (no second store): the
-- original workbook stays on the PC, and only the form's structure and its
-- PC-side location reference are written here.
--
-- Additive only: an existing row keeps kind 'skill', which is what it is. No
-- table rebuild and no UPDATE of stored content.

ALTER TABLE b66_saved_quote_skill ADD COLUMN skill_kind TEXT NOT NULL DEFAULT 'skill';
