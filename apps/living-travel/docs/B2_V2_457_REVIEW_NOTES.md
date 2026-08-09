# B2 Living Travel V2 — Issue #457

## Status

```text
B2_V2_UI_REVIEW_READY
OWNER_UI_APPROVED=false
UX_BLOCKED_BY_OWNER_UI_DECISION
BACKEND_IMPLEMENTATION_PRESERVED
PR_OPEN_DRAFT_UNMERGED
```

## Art direction

**PLACE → ROUTE → DAY → ADAPT**

The V2 participant experience is rebuilt around movement through a place rather than generic travel cards:

- destination and coordinates establish place immediately;
- route/time/neighborhood cues carry the spatial language across screens;
- preference capture shapes trip character instead of presenting a generic chip grid;
- the current Edition is treated as the primary journey object;
- Edition Read is organized by day, neighborhood, time, route and editorial rationale;
- feedback changes route density, transfers, local depth and dwell time visibly;
- archive preserves how the same destination changed across editions;
- operator queue/review reuses the route language while remaining denser and utilitarian.

## Owner-facing QA boundary

Visible `UI Preview`, `Synthetic Preview`, and demo-banner chrome is removed from the redesigned owner-facing surfaces. Historical test markers are retained only as visually hidden text where required by legacy static contracts.

## Scope

Only `apps/living-travel/**` is changed. Backend/Auth/DB/provider/deployment workflow contracts are not modified.

## Validation state

Repository compare confirms the branch is based on the then-current `main` SHA `0654025bb35c5352154ce0bfa9788d6792c3fd21` and all changed files are inside `apps/living-travel/**`.

This implementation was performed through the GitHub connector. Local Chromium and pytest execution were not available in that environment, so a real-browser/CI gate is still required before technical merge. Technical QA does not constitute owner visual approval.
