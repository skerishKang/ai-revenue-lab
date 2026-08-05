# Motion specification — Report-to-Urgency-Support-Record

## Sequence

1. source report
2. provenance
3. observable indicators
4. conflicting evidence
5. missing information
6. clarification need
7. provisional rationale
8. human correction
9. unresolved uncertainty retention
10. HUMAN-REVIEWED URGENCY SUPPORT RECORD

## Deterministic timing

Each step uses the same 80 ms `motion-reveal` animation. Delays are fixed at `0, 75, 150, 225, 300, 375, 450, 525, 600, 680 ms`. The final element therefore completes nominally at `760 ms`.

No fixed completion timeout is used. The final step's actual `animationend` event, filtered by both target and animation name, is the only completion authority in standard-motion mode.

## Replay contract

- The class reset and forced style read produce the same initial state on every replay.
- Replay 1 and Replay 2 must end with equal computed opacity, transform and box-shadow values for every step.
- Geometry must remain equal because animation changes opacity, transform and inset shadow only; layout dimensions do not change.
- Focus remains on the replay control and no focus transfer occurs.
- The script does not call scrolling APIs. Focus is requested with `preventScroll` only for tab navigation.
- Completion metadata records focus and scroll stability.

## Reduced motion

With `prefers-reduced-motion: reduce`, all sequence information is immediately visible and complete. The reduced-motion path does not wait for animation and records `reduced-motion immediate information-complete` as completion authority.

## Persistent post-completion information

The following remain visible after every completion:

- CONFLICTING EVIDENCE
- MISSING INFORMATION
- UNRESOLVED UNCERTAINTY
- FINAL PRIORITY AUTHORITY — HUMAN ONLY
- NO AUTONOMOUS TRIAGE
- NO DISPATCH OR RESOURCE ALLOCATION
