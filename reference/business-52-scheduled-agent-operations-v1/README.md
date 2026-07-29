# Business 52 · Scheduled Agent Operations — Phase 1 visual reference

Static `UI_ONLY` reference for Proposed Business 52.

## Result

`HUMAN-APPROVED SCHEDULED OPERATION RUNBOOK`

## Scope and authority

- Parent: #154
- Product decision: #304
- Phase 1 execution contract: #305
- Scope: `reference/business-52-scheduled-agent-operations-v1/**`
- Stable slug: `scheduled-agent-operations`
- Visual direction: `Scheduled Operations Timeworks / 예약 운영 시간공방`

This reference uses a wholly fictional organization (Maru Research Office) and one synthetic operation (weekday 08:00 supplier-risk digest preparation). It performs no live scheduling, background execution, account access, notification, integration, storage, analytics, model execution or deployment.

## States

`cover`, `schedule`, `inputs`, `run`, `exceptions`, `decision`, `mobile`

## Review

Open `index.html`. Tabs support click, ArrowLeft, ArrowRight, Home and End. The decision state contains the deterministic `Schedule-to-Approved-Operation-Runbook` signature motion.

## Self-check

```bash
python tests/validate_reference.py
python tests/browser_self_check.py
```

These are implementation self-checks, not independent Local Validation or UI approval.
