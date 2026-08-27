# Business 41 · Foreign Emergency Assistant / 외국인 긴급신고 도우미

Phase 1 `UI_ONLY` static visual reference for a **Multilingual Emergency Reporting Desk**.

## Product result

`HUMAN-READY EMERGENCY REPORTING BRIEF`

This workspace shows how one wholly synthetic foreign-language user prepares information for a human official emergency-service handoff. It does **not** place a call, open chat, capture audio, translate live speech, access location, classify urgency, dispatch resources, give medical/police/fire/legal advice, verify identity, or infer immigration status.

## Exact seven states

`cover` · `language` · `situation` · `location` · `critical` · `handoff` · `mobile`

## Synthetic fixture

- Luis — fictional adult visitor
- Preferred language: Spanish — synthetic
- Korean interface with English support labels
- Smoke visible near a closed maintenance room in a fictional transit annex
- Partially known synthetic location
- People status unknown
- Emergency connection not active

## Local review

```bash
python tests/validate_reference.py
python tests/browser_self_check.py
```

The browser harness serves the exact local files from a loopback HTTP server and checks 7 states × 3 viewports. Implementation self-check is not an independent `LOCAL_VALIDATION_PASS`.

## Phase boundaries

- `UI_REVIEW_READY`
- `NOT_VALIDATED_BY_LOCAL`
- `NOT_DEPLOYED_PENDING_UI_APPROVAL`
- `UX_NOT_STARTED`
- `BACKEND_FROZEN`
- `DO_NOT_MERGE`
