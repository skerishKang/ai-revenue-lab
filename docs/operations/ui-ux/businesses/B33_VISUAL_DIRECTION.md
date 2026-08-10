# B33 — Research Memory Visual Direction

Status: `DIRECTION_FROZEN · REVIEW_AUTHORITY`  
Verdict: `REDESIGN_ART_LAYER`

Preserve canonical `question → sources → claims → note` UX authority and source/claim review contracts. Replace the generic light prototype shell with a research-specific trace environment.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh platform-family audit run `31422928265`, artifact `9076118820`
- canonical `https://33-research-memory.pages.dev/`
- review authority PR #411 head `c034ccae74d038bb3c5517c62e3c290db5bffc2a`
- numbered migration intentionally serves the UX entry as root.

Current UX is clear but visually generic: large heading + white cards. It does not yet make research memory/lineage the dominant object.

## Product thesis

A research question becomes a durable memory only when selected sources, accepted/rejected claims and the resulting note remain traceable to one another.

Core object: **the research trace: question → source → claim → note**.

## Reserved territory — Research Trace Desk

- source slips/citations with date/provenance
- claim fragments connected to source evidence
- accepted/rejected state visible without traffic-light dashboard cliché
- note card/page retains source lineage
- temporal memory cue for returning later

Avoid generic research cards, chat, note app, academic PDF viewer and B15 newsroom/B48 gate aesthetics.

## Key surfaces

- Question: one research question and scope.
- Sources: source slips with reason for selection.
- Claims: claim/evidence linkage and rejection correction.
- Note: provisional note visibly derived from accepted claims.
- Return/memory: later retrieval should preserve lineage.

## Differentiation

B15 produces a briefing; B33 preserves personal research memory. B48 verifies a claim as infrastructure. B57 compares translation text.

## Acceptance criteria

1. trace/lineage is visible without reading technical explanation;
2. source-to-claim relationship remains inspectable;
3. rejected claim and corrected claim are visually distinct;
4. final note retains source references;
5. generic white-card prototype identity is replaced;
6. Mobile keeps question→source→claim→note order;
7. current authority/state/reset contracts remain intact.
