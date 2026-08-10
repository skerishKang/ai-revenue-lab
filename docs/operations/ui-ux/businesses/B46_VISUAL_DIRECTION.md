# B46 — AI Personalization Engine Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh platform audit: run `31422928265`, artifact `9076118820`, canonical `https://46-ai-personalization-engine.pages.dev/`. Current generic light cards do not make user control/personalization causality visible.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A user inspects explicit preferences, compares content before/after a change, understands why it changed and retains control to adjust or undo it.

```text
PREFERENCES → BEFORE / AFTER → WHY CHANGED → MY CONTROL
```

Core object: **the preference control + live before/after content preview**.

## Reserved territory — Preference Control Mixer

- explicit user-owned preference channels/sliders/toggles
- content preview changes beside controls
- reason/explanation attached to changed content
- Undo/Reset always visible
- no opaque recommendation score

Avoid generic cards, algorithm dashboard, social feed, B06 world-dispatch style and dark control room.

## Acceptance criteria

1. changing a preference visibly changes content preview;
2. explanation attaches to exact changed item;
3. user control/undo/reset remains obvious;
4. generic B45–B49 template is gone;
5. Mobile pairs current control with changed preview;
6. no sensitive-trait inference or hidden scoring is introduced.
