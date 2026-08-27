# Motion specification

## Signature

`Fleet-Inventory-to-Approved-Operations-Plan`

## Sequence

1. devices and models;
2. eligibility;
3. planned jobs;
4. capacity estimates;
5. availability;
6. failure and quarantine;
7. bounded retry and duplicate prevention;
8. human release;
9. `HUMAN-APPROVED LOCAL MODEL FLEET OPERATIONS PLAN`.

## Timing

- trace nodes: 110ms each, staggered from 0ms to 560ms;
- final record: 120ms with a 640ms delay;
- nominal final completion: 760ms;
- normal completion authority: final record `animationend` where `animationName === fleetPlanComplete`;
- no fixed completion timeout;
- reduced motion: immediate information-complete state;
- replay: deterministic reset by class removal, layout flush and class re-application;
- focus, scroll and geometry are not programmatically changed.

## Persistent boundaries

`MODEL QUARANTINED`, `WORKER UNAVAILABLE`, `JOB NOT EXECUTED`, `NO AUTOMATIC SCALE-UP`, `FLEET ACTIVATION WITHHELD`, `DUPLICATE JOB PROHIBITED`, and `HUMAN RELEASE AUTHORITY` remain visible after completion.
