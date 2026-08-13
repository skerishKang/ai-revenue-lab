# Translation Weave Motion Specification

## Purpose

`Translation Weave / 번역 결 엮기` shows that a literary translation is assembled from traceable source choices rather than appearing as an unexplained result.

## Measured timing contract

The browser validator reads `animation-duration` and `animation-delay` from computed styles while `data-motion-state="running"` is active.

| Layer | Duration | Delay | Computed end |
|---|---:|---:|---:|
| thread 1 | 480ms | 0ms | 480ms |
| thread 2 | 480ms | 100ms | 580ms |
| thread 3 | 480ms | 200ms | 680ms |
| rendering 1 | 300ms | 180ms | 480ms |
| rendering 2 | 300ms | 280ms | 580ms |
| rendering 3 | 300ms | 380ms | 680ms |

```text
Computed maximum end: 680ms
Completion authority: animationend from .rendering-3 / settle-rendering
Fixed completion timeout: none
```

## State machine

```text
complete
→ running
→ complete
```

- The complete state is the stable information state.
- Replay briefly applies the running state after a forced style recalculation.
- The final rendering layer's `animationend` event returns the board to complete.
- Repeated replay reaches the same complete frame.

## Stable geometry contract

The following remain fixed before, during and after replay:

- source fragment boxes;
- chosen-rendering boxes;
- final translated paragraph;
- review rail;
- replay control;
- document height;
- focus position;
- scroll position.

No whole-state opacity, transform, layout, text-position or container-size animation is allowed.

## Animated properties

Only these evidence layers animate:

- SVG path `stroke-dashoffset` and opacity for `.thread`;
- inset proof emphasis for `.rendering` boxes.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- the board stays in `complete`;
- paths are fully drawn immediately;
- rendering emphasis is immediately present;
- the same source, translation and annotation information remains visible;
- replay keeps focus and scroll stable.

## Browser assertions

`evidence/validate_browser.py` verifies:

- computed maximum end equals 680ms;
- running and complete state transitions occur;
- no `setTimeout` controls completion;
- first and second replay final styles are identical;
- normal and reduced-motion final styles are equivalent;
- geometry, document height, focus and scroll remain stable;
- deterministic motion frames and a GIF are generated from the validated runtime.
