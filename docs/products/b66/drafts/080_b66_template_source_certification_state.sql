-- DRAFT — #3595 follow-up. NOT part of the applied migration sequence yet.
--
-- Move this file into apps/padiem-chat/migrations/ only after the CTO orders
-- the next D1 gate run (the same gate that applies 078/079). It is kept under
-- docs/ so a Chat deploy lane cannot pick it up by accident.
--
-- Additive only: three ALTER TABLE ... ADD COLUMN statements, no table rebuild,
-- no DROP, no backfill UPDATE. An existing row keeps NULL state, which reads as
-- "no certification recorded" and never as a pass.
--
-- States (source: #3595 body, "Certification states"):
--   ANALYZED · REPRODUCTION_IN_PROGRESS · CERTIFIED ·
--   CERTIFIED_WITH_TOLERANCE · REJECTED
--
-- See docs/products/b66/CERTIFICATION_STATE_080_DESIGN.md for transitions,
-- the tolerance record shape and the fail-closed rules.

ALTER TABLE b66_template_source ADD COLUMN certification_state TEXT
    CHECK (certification_state IS NULL OR certification_state IN (
        'ANALYZED',
        'REPRODUCTION_IN_PROGRESS',
        'CERTIFIED',
        'CERTIFIED_WITH_TOLERANCE',
        'REJECTED'));

-- Evidence JSON: gate results, measured deltas, and — only when the owner
-- reviewed a deviation — the accepted-differences record.
--
-- No length CHECK. A byte cap here would be an arbitrary number that can reject
-- a legitimate record; the only real bound is D1's 2 MiB row limit. Measured
-- for scale: the public synthetic fixture's certification JSON (13 gates plus
-- their detail) is 820 bytes, and even a tolerance record with per-area entries
-- stays around 2 KiB — about 0.1% of a row. Only JSON validity is enforced, so a
-- truncated or hand-edited blob fails closed while a long evidence list does not.
ALTER TABLE b66_template_source ADD COLUMN certification_evidence_json TEXT
    CHECK (certification_evidence_json IS NULL
           OR json_valid(certification_evidence_json));

ALTER TABLE b66_template_source ADD COLUMN certification_updated_at TEXT;
