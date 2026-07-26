# Motion specification — Page Fold / 지면 넘김

## Purpose

Express the change from the front page to an inside family-news page using restrained print behavior. The motion is a visual review state only; it does not define final navigation or reading UX.

## Trigger

- Review-state button: `지면 넘김`
- Replay button: `지면 넘김 재생`
- Keyboard shortcut while the Page Fold state is active: `R`

## Timing

- Total duration: `680ms`
- Accepted requirement range: `550–750ms`
- Easing: `cubic-bezier(0.58, 0.01, 0.22, 1)`

## Visual phases

1. `0–45%`: front sheet begins moving left with a restrained Y-axis turn and growing edge shadow.
2. `45–100%`: front sheet narrows through clipping, exits left, and reveals the inside page.
3. Persistent orientation rail remains visible throughout with masthead and page location.

## Implementation

- CSS `transform`, `clip-path`, `opacity`, and `filter`
- One state class applied by minimal JavaScript
- No canvas, external animation library, or runtime asset request

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- no travel, rotation, clipping animation, or delayed transition;
- front sheet is immediately hidden;
- the inside page becomes visible in the same location;
- persistent masthead/location rail remains visible;
- label changes to `가족 소식면 · 이동 없이 전환`.

## Non-goals

- realistic page-curl physics;
- drag gesture;
- pagination system;
- reading-progress persistence;
- final page-navigation semantics.
