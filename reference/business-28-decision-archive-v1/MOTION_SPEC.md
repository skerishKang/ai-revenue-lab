# Reason Chain Lock / 이유 사슬 잠금

## Purpose

Make the decision structure legible without implying automated judgment.

## Sequence and nominal timing

1. option slips: 0–400ms including stagger;
2. reason connectors: 180–360ms;
3. accepted/rejected reasons: 260–440ms;
4. unresolved assumption: 350–510ms;
5. dissent margin: 420–580ms;
6. owner/deadline: 500–640ms;
7. revisit trigger: 570–690ms;
8. final decision seal: 650–750ms.

The final `reasonSeal` animation on `#decision-seal` is the only normal completion authority. JavaScript listens for its `animationend`, then moves `data-motion-state` from `running` to `complete`. No fixed timeout is used.

## Replay contract

- accepted starting states: `idle` or `complete`;
- replay removes the old `complete` and `running` class through `setMotionState('idle')`;
- one layout read plus `requestAnimationFrame` starts the deterministic `running` sequence;
- the final seal event sets `complete`;
- rejected reasons, dissent and unresolved assumptions remain visible in complete state.

## Reduced motion

`prefers-reduced-motion: reduce` bypasses the running sequence and immediately applies complete state. CSS also collapses any animation duration/delay and preserves equivalent information.
