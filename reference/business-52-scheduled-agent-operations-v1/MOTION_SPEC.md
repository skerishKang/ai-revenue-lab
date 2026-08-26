# Motion specification

## Signature

`Schedule-to-Approved-Operation-Runbook`

## Sequence

1. objective and owner;
2. timezone and cadence;
3. authorized inputs;
4. trigger and condition watch;
5. planned run and evidence;
6. failure/skip/suppression distinctions;
7. retry, pause and manual override;
8. `HUMAN-APPROVED SCHEDULED OPERATION RUNBOOK`.

## Timing

- trace nodes: 110ms each, staggered from 0ms to 660ms;
- final record: 120ms with a 660ms delay;
- nominal final completion: 780ms;
- normal completion authority: final record `animationend` where `animationName === runbookComplete`;
- no fixed completion timeout;
- reduced motion: immediate information-complete state;
- replay: deterministic reset by class removal, layout flush and class re-application;
- focus, scroll and geometry are not programmatically changed.

## Persistent boundaries

`NOT SCHEDULED`, `NOT EXECUTED`, `CONDITION NOT MET`, `SKIPPED — NOT PASSED`, `NOTIFICATION SUPPRESSED`, `DUPLICATE RUN PROHIBITED`, `PAUSE AUTHORITY — HUMAN ONLY`, and `EXECUTION WITHHELD` remain visible after completion.
