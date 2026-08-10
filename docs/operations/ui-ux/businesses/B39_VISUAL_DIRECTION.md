# B39 — 112 Real-Time Interpretation Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://39-112-real-time-interpretation.pages.dev/`. Current generic card template fails to express the bilingual call workflow.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

During a bounded emergency-call interpretation demo, original speech and interpreted meaning stay visible together until operator/human handoff; interpretation is assistive, not autonomous dispatch authority.

```text
CALL → ORIGINAL / INTERPRETATION → REVIEW → OPERATOR HANDOFF
```

Core object: **the bilingual call timeline**.

## Reserved territory — Bilingual Call Console

- original and interpretation side-by-side or line-paired
- timestamps/waveform segments as temporal anchors
- uncertainty/clarification marker on exact utterance
- operator confirmation/handoff status
- emergency clarity without alarmist decoration

Avoid chat bubbles, generic translator app, black control-room spectacle and language score dashboards.

## Acceptance criteria

1. original and interpreted content remain simultaneously visible;
2. timing/utterance correspondence is obvious;
3. uncertainty/clarification attaches to exact segment;
4. operator handoff remains human authority;
5. Mobile preserves bilingual pairing;
6. no implication of real 112 connection beyond current contract.
