# Padiem Claw Operations Runbook

## Normal run

1. Resolve canonical subject/entitlement where required.
2. Resolve repository and exact revision intent.
3. Create B54 run in `QUEUED`.
4. Cloud: allocate bounded sandbox lease; run becomes `PREPARING`.
5. Build canonical P01 request; never inject provider route from user input.
6. Observe P01 `RUN_STARTED` before projecting `RUNNING`.
7. Project normalized progress only.
8. On approval pause, expose `WAITING_APPROVAL`; resume only through canonical continuation.
9. Collect bounded diff/test/evidence artifacts.
10. Complete, fail or cancel exactly once; release sandbox lease.
11. GitHub mutation, when enabled, defaults to branch + Draft PR.

## Operator checks

- run/trace correlation
- lease ownership and expiry
- queue age and execution timeout
- test/evidence presence
- outstanding approval
- sandbox release after terminal state
- no unexpected network/write permission expansion

## Failure handling

- mismatched event: fail closed and retain safe audit metadata
- sandbox allocation failure: fail without claiming execution
- expired lease: allocate a new authorized lease; never revive old one
- P01 failure: bounded user-safe failure with correlation ID
- provider outage: P01/B14 routing/recovery authority handles it
- GitHub write failure: preserve verified result; do not blindly retry destructive mutation

No direct secret copying, terminal-state resurrection, auto-merge, or approval bypass.
