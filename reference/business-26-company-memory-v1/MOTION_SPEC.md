# Memory Thread Reconstruction / 기억 실마리 복원

## Purpose

The motion demonstrates that an institutional memory is reconstructed from records and recollections rather than generated as one seamless authoritative story.

## State contract

```text
idle or complete
→ running
→ complete
```

Replay removes the previous complete class before adding the running class. Completion is sourced from the `animationend` event on the final human-review element. Reduced motion bypasses animation and paints the complete state immediately.

## Sequence

1. fixed event anchor remains visible and stationary;
2. contemporary source slips align;
3. decision context appears;
4. later recollection arrives;
5. contradiction remains visible;
6. later consequence connects;
7. human review resolves last.

## Computed timing

The browser validator reads `animation-delay` and `animation-duration` from computed styles for every animated step. The final visual end must be between 680ms and 760ms. The evidence file `evidence/motion-timing.json` is generated from the browser runtime, not manually entered.

## Stability contract

During replay the validator records:

- event-anchor bounding box;
- reconstruction container bounding box;
- page scroll position;
- focused replay control;
- source-ID visibility;
- contradiction visibility;
- missing-evidence visibility.

These values must remain stable within deterministic tolerance.

## Reduced motion

`prefers-reduced-motion: reduce` disables animation, immediately exposes all final evidence layers, sets the human-review mark visible, preserves focus and geometry, and records the motion state as complete.
