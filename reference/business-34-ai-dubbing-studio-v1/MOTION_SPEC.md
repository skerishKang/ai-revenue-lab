# Motion Spec — Source-to-Localized-Master

## Contract
`idle|complete → running → complete`

Replay control: `#replay-master`
Motion root: `#master-motion`
Final element: `#localized-master-seal`

## Sequence
1. source rights
2. speaker map
3. transcript correction
4. translation timing
5. synthetic voice direction
6. pronunciation correction
7. timing drift retained
8. release exception retained
9. `HUMAN-APPROVED LOCALIZED MASTER`

## Authority
Normal completion is authorized only by the final element's `masterSeal` `animationend`. No `setTimeout` or `setInterval` is used.

Computed final end: `690ms delay + 90ms duration = 780ms`.

Replay removes previous `running` and `complete` before restart. Reduced motion immediately applies information-complete state. `TIMING DRIFT`, `RELEASE EXCEPTION`, and `SYNTHETIC VOICE — AUTHORIZED` remain visible after completion.
