# Motion Specification — Experience-to-Improvement Trace

## State contract

`idle|complete → running → complete`

Replay removes `is-running` and `is-complete`, sets `data-motion-state="idle"`, forces style recalculation, then starts the deterministic sequence.

## Sequence and nominal timing

| Step | Delay | Duration | End |
|---|---:|---:|---:|
| official procedure | 0ms | 120ms | 120ms |
| citizen experience | 90ms | 120ms | 210ms |
| staff experience | 180ms | 120ms | 300ms |
| official/field evidence alignment | 270ms | 120ms | 390ms |
| contradiction/missing/unverified | 360ms | 120ms | 480ms |
| repeated bottleneck | 450ms | 120ms | 570ms |
| improvement hypothesis and metric | 540ms | 120ms | 660ms |
| HUMAN-REVIEWED FOLLOW-UP seal | 640ms | 140ms | 780ms |

Normal completion authority is `.follow-up-seal` receiving `animationend` with `animationName === "followUpComplete"`. No fixed timeout is used as normal completion authority.

## Stability contract

- fixed trace grid geometry before, during and after replay;
- no whole-page fade;
- replay retains button focus and page scroll;
- citizen experience, staff counterpoint, contradiction, missing evidence and uncertainty remain visible at completion;
- Replay 1 and Replay 2 must produce equivalent computed final styles.

## Reduced motion

`@media (prefers-reduced-motion: reduce)` exposes all trace layers immediately. JavaScript detects the preference and enters `complete` directly.
