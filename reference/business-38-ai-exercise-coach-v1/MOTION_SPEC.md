# Motion Specification — Profile-to-Adaptive-Movement-Plan

## Purpose

Show the information-authority sequence from self-reported profile to a human-reviewed adaptive movement plan while retaining unknowns, stop boundaries, non-medical disclosure and regression choice.

## Sequence

1. user goal and constraints
2. non-diagnostic observation
3. session sequence
4. general form cue
5. exertion check
6. regression/progression user choice
7. review correction
8. unknowns and stop boundary retention
9. HUMAN-REVIEWED ADAPTIVE MOVEMENT PLAN

## Timing and authority

- Nominal completion: 780 ms.
- Steps 1–8: 80 ms each, staggered from 0–560 ms.
- Final element: `motionFinal`, 100 ms duration with 680 ms delay.
- Completion authority: the final element’s actual `animationend` event with `animationName === "motionFinal"`.
- No fixed completion timeout exists.
- The track records `data-completion-authority="animationend:motionFinal"` after completion.

## Deterministic replay

Before each replay the implementation removes running/completed classes, forces style recalculation with `offsetWidth`, and re-adds the running class. Final styles and geometry therefore resolve from the same class state on Replay 1 and Replay 2.

## Stability

- Replay does not focus another element.
- The replay button keeps focus.
- Scroll coordinates are captured and restored without animated scrolling.
- Motion uses opacity, transform and a final box-shadow only; layout geometry is unchanged.

## Reduced motion

When `prefers-reduced-motion: reduce` matches, the motion completes immediately with full information visibility and `data-completion-authority="reduced-motion-immediate"`. The same final labels remain visible.

## Persistent authority labels

- UNKNOWN / NOT ASSESSED
- STOP OR PAUSE CONDITION
- NOT MEDICAL ADVICE
- REGRESSION OPTION
