# Motion specification — Turning Point Sweep / 승부처 스윕

Status: `reference-only` · Phase 1 visual motion preview

## Concept

A single restrained sweep connects the decisive match timeline event, the relevant tactical zone and the selected player note while the page geometry remains fixed.

## Timing

- Total duration: `680ms`
- Timeline activation: `0–180ms`
- Turning-point underline/sweep: `120–390ms`
- Decisive field zone: `250–540ms`
- Player note reveal: `500–680ms`
- Primary easing: `cubic-bezier(.22,.78,.18,1)`

## Animated properties

- `opacity`: timeline marks, field zone and player note.
- `transform`: maximum 8px local translation; no page or viewport movement.
- `clip-path`: restrained coral underline sweep.
- `filter`: subtle contrast emphasis only on the decisive field zone.

## Prohibited effects

No ball-flight animation, fireworks, score explosion, 3D stadium, particles, bounce, spring or scroll movement.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- all transition/animation durations are effectively immediate;
- the timeline, sweep, decisive zone and player note appear in their completed state;
- no translation or clip travel occurs;
- the replay control remains keyboard operable.

## Review control

The `승부처 스윕 재생` button restarts the deterministic visual sequence. It does not load, calculate, save or alter sports data.
