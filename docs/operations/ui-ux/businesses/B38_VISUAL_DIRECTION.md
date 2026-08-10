# B38 — AI Exercise Coach Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://38-ai-exercise-coach.pages.dev/`. Current generic light cards do not make exercise/session behavior visually specific.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

User constraints shape a bounded exercise session; the user performs it, adjusts difficulty/comfort and reviews the session without medical diagnosis or body judgment.

```text
PROFILE / CONSTRAINTS → SESSION → ADJUST → REVIEW
```

Core object: **the movement session sequence with time/reps/rest and user adjustments**.

## Reserved territory — Movement Session Canvas

- exercise sequence/timer/reps/rest visible as a kinetic but calm session strip
- movement diagrams/pose silhouettes only when neutral and instructional
- constraint markers stay near affected exercises
- user comfort/difficulty adjustment changes session visibly

Avoid fitness influencer imagery, weight-loss/body scoring, medical dashboard, neon gym UI and generic cards.

## Acceptance criteria

1. active session sequence is visually central;
2. constraints visibly affect exercise selection/intensity;
3. adjustment changes session plan immediately;
4. body-neutral/non-medical framing remains explicit;
5. Mobile prioritizes current exercise and next/rest context;
6. current safety/interaction contracts remain intact.
