## B2 Living Travel V2 — Issue #457

This is an owner-rejected UI art-direction reset, not a polish pass.

```text
B2_V2_UI_REVIEW_READY
OWNER_UI_APPROVED=false
UX_BLOCKED_BY_OWNER_UI_DECISION
BACKEND_IMPLEMENTATION_PRESERVED
PR_OPEN_DRAFT_UNMERGED
```

### New visual grammar

**PLACE → ROUTE → DAY → ADAPT**

- Canonical entry now communicates Busan, coordinates, neighborhoods, route and pace immediately.
- Preferences shape trip character rather than presenting a generic chip grid.
- Generation visualizes preference interpretation into route/day structure.
- Traveler Home makes the current Edition the primary journey object.
- Edition Read is rebuilt around day, neighborhood, time, route and editorial rationale.
- Feedback becomes an editorial brief; comparison shows route density, transfer count, local depth and dwell-time changes.
- Archive treats prior Editions as versions of the same journey rather than database cards.
- Traveler and Operator entry surfaces no longer expose visible QA/debug chrome.
- Operator queue/review reuse the route language while staying denser and utilitarian.

### Scope

All changes are under `apps/living-travel/**`. No Backend/Auth/DB/provider/deployment workflow changes.

### Validation

The branch was created from `main` SHA `0654025bb35c5352154ce0bfa9788d6792c3fd21`. Repository compare confirms the branch is ahead only with Living Travel files.

This work was executed through the GitHub connector, so local Chromium/pytest execution was not available. CI and real-browser desktop/tablet/mobile validation remain required before technical merge. Technical validation will not constitute owner approval.
