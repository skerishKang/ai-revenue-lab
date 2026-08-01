# MOTION_SPEC.md

## Question-to-Official-Route / 질문에서 공식 경로로

Review state: `source-map`
Replay control: `#replay-route`
Motion root: `#route-motion`
Completion authority: `#route-seal` `animationend` where `animationName === "routeSeal"`

## State contract

```text
idle|complete → running → complete
```

Replay removes both `complete` and `running`, records `idle`, forces a deterministic style flush, then applies `running`. No timeout or interval is used for normal completion.

## Nominal sequence

| Stage | Delay | Duration | Nominal end |
|---|---:|---:|---:|
| question situation pieces | 0–90ms | 210ms | 300ms |
| jurisdiction/freshness checks | 110ms | 170ms | 280ms |
| official source | 220ms | 170ms | 390ms |
| office and procedure | 330ms | 170ms | 500ms |
| preparation and exception | 440ms | 150ms | 590ms |
| excluded wrong route | 520ms | 130ms | 650ms |
| human confirmation | 590ms | 130ms | 720ms |
| final reviewed-route seal | 680ms | 90ms | **770ms** |

## Persistent completed information

Official source, possible exception, excluded route and human confirmation remain visible after completion.

## Reduced motion

`prefers-reduced-motion: reduce` suppresses meaningful animation duration. The replay handler immediately applies the complete state and preserves the same information.

Independent Local Validator must remeasure computed timing, geometry, scroll, focus and Replay 1/2 equivalence at the exact PR head.
