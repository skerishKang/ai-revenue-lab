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

-- Bounded evidence JSON: gate results, measured deltas, and — only when the
-- owner reviewed a deviation — the accepted-differences record.
ALTER TABLE b66_template_source ADD COLUMN certification_evidence_json TEXT
    CHECK (certification_evidence_json IS NULL
           OR length(certification_evidence_json) <= 8192);

ALTER TABLE b66_template_source ADD COLUMN certification_updated_at TEXT;
