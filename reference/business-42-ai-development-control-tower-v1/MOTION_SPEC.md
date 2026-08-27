# Motion Spec — Work-Order-to-Controlled-Decision

## Review control

- Replay control: `#replay-control-record`
- Motion root: `#control-motion`
- Final element: `#control-record-seal`
- State contract: `idle|complete → running → complete`

## Sequence

1. work order
2. exact source authority
3. role assignment
4. implementation report
5. independent evidence
6. blocker and gate review
7. human decision
8. next authorized action
9. `HUMAN-APPROVED DEVELOPMENT CONTROL RECORD`

## Completion authority

Normal completion is authorized only by the final element's `controlSeal` `animationend` event. The JavaScript contains no fixed completion `setTimeout` or `setInterval`.

Nominal computed final end:

```text
700ms delay + 90ms duration = 790ms
```

Replay removes prior `running` and `complete` classes before the new run. Replay does not move focus, alter scroll position or change layout geometry. Replay 1 and Replay 2 must resolve to equal final computed opacity and transform.

## Reduced motion

`prefers-reduced-motion: reduce` immediately applies the information-complete state without sequencing.

The following remain visible in idle, running and complete states:

- `STALE EVIDENCE — DO NOT USE`
- `BLOCKER`
- `UX NOT AUTHORIZED`
- `BACKEND FROZEN`
- `MERGEABLE ≠ MERGE AUTHORIZED`
- `DEPLOYMENT AUTHORIZED — NOT EXECUTED`
