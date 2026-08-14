# B6–B12 static authority regression scope

Issue #623 changes only Portfolio Console static number authority for Businesses 6–12.

The executable regression is `test_b6_b12_canonical_identity.py`. It verifies:

- B6–B12 ordered mappings remain unchanged;
- all seven manifest entries use `NA.CANONICAL`;
- B6 keeps `world-feed`, `apps/world-feed/`, `research`, and the Personal World Discovery positioning boundary already documented in `apps/README.md`;
- B7–B12 keep their existing `reference/business-XX-...-v1/` workspaces and do not gain duplicate `apps/` workspaces;
- lifecycle/state are not promoted by the numbering correction;
- the manifest mappings remain present in the canonical registry section.

This file records test intent only. It does not authorize UI, UX, backend, deployment, or product-runtime changes.