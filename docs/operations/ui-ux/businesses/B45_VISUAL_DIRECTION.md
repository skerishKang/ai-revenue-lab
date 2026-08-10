# B45 — AI Content Engine Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh platform audit: run `31422928265`, artifact `9076118820`, canonical `https://45-ai-content-engine.pages.dev/`. Current root/UX uses the same generic light header + large H1 + cards as B46–B49.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

One source enters a reusable content engine, is transformed into a requested format, reviewed and kept traceable to the original.

```text
ORIGINAL → FORMAT CONTRACT → DRAFT → REVIEW → OUTPUT LINEAGE
```

Core object: **the content lineage rail from source to reviewed output**.

## Reserved territory — Content Lineage Engine

- stable source rail on one side
- transform/format contract in the middle
- output proof on the other side
- visible source references preserved through transformation
- technical/internal engine tone, not creator lifestyle UI

Avoid generic cards, black-box “generate” button, B12 creator editorial desk duplication and B22 story-spine duplication.

## Differentiation

B12 is creator-facing multi-format production. B22 is narrative spine across media. B45 is reusable internal transformation infrastructure with lineage.

## Acceptance criteria

1. source→transform→output lineage visible at a glance;
2. format contract materially changes output presentation;
3. review remains a human gate;
4. generic card template is gone;
5. Mobile preserves source and current output context;
6. current engine/state boundaries remain intact.
