# B37 — AI Safe Route Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://37-ai-safe-route.pages.dev/`. Current generic cards do not express routing and visually duplicate neighboring safety prototypes.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

The user compares bounded route evidence and chooses a route; the product must not claim an objectively “safest” route.

```text
DEPARTURE → ROUTE COMPARISON → MY CHOICE → CONFIRM
```

Core object: **two or more visible route paths with evidence attached to segments**.

## Reserved territory — Evidence Route Map

- map/route geometry is primary
- time, lighting, crowd, visibility or known data attached to route segments
- evidence availability/unknowns explicit
- user choice highlighted after comparison

Avoid red danger heatmaps, crime scoring, surveillance aesthetics, generic card comparisons and autonomous safest-route labels.

## Acceptance criteria

1. actual route paths dominate the working surface;
2. evidence is attached spatially to paths;
3. missing/unknown evidence is explicit;
4. user—not model—makes final choice;
5. Mobile supports route comparison without hiding evidence;
6. safety/legal boundaries remain intact.
