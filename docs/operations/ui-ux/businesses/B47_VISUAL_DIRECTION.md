# B47 — Real-Time Feedback Engine Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh platform audit: run `31422928265`, artifact `9076118820`, canonical `https://47-real-time-feedback-engine.pages.dev/`. Current generic card template hides the product's event→theme→proposal logic.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

Individual feedback events remain visible, conflicting/missing feedback is preserved, bounded themes are proposed and a human decides whether to apply a change.

```text
FEEDBACK EVENTS → THEMES / CONFLICTS → CHANGE PROPOSAL → MANUAL PREVIEW / APPLY
```

Core object: **the feedback signal basin where events cluster without erasing disagreement**.

## Reserved territory — Feedback Signal Basin

- individual events enter as small source traces
- themes form as groups, not hidden aggregate scores
- conflicts/missing evidence remain visible
- candidate change proposal appears beside affected product area
- manual preview/apply gate

Avoid sentiment certainty, employee/customer scoring, surveillance timeline, engagement dashboard and generic cards.

## Acceptance criteria

1. individual feedback remains traceable into themes;
2. conflict/missing feedback cannot disappear;
3. no automatic winner/action;
4. proposal preview shows what would change;
5. generic prototype shell is replaced;
6. current human-only execution boundary remains intact.
