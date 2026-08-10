# B52 — Scheduled Agent Operations Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://52-scheduled-agent-operations.pages.dev/`. Current generic card layout does not express schedules, conditions and run exceptions.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A scheduled agent run is understandable before execution: when it runs, what it may do, what it may not do, what exception occurred and when a human must review.

```text
SCHEDULE → RUN PREVIEW → EXCEPTION / CONDITION → HUMAN REVIEW
```

Core object: **the time rail / runbook**.

## Reserved territory — Time Rail Operations

- calendar/time axis and next-run marker
- bounded action/permission lane
- condition/exceptions attached to exact run
- run preview before execution
- human review lane for exceptions

Avoid control-tower duplication, generic task cards, cron-expression-first developer UI and autonomous-agent spectacle.

## Differentiation

B42 = many development work items; B52 = recurring time-based runs. B55 = local hardware fleet availability.

## Acceptance criteria

1. schedule/time is visible as the primary structure;
2. next run and allowed/prohibited actions are explicit;
3. exception attaches to a specific run;
4. human review path remains clear;
5. generic systems template is gone;
6. Mobile becomes a chronological runbook;
7. current scheduling/authority contracts remain intact.
