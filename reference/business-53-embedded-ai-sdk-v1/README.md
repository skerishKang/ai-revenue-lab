# Business 53 · Embedded AI SDK — Phase 1 visual reference

Static, synthetic `UI_ONLY` reference for **Embedded Capability Fit Bench / 기존 제품 AI 장착 설계실**.

## Product result

`HUMAN-APPROVED EMBEDDED AI INTEGRATION CONTRACT`

## Synthetic host fixture

- Organization: Naru Culture Office — fictional
- Host product: Naru Program Guide — synthetic
- Proposed mount point: program-detail side rail
- Approved capability: explain selected program requirements and draft a review checklist
- Model/provider: not selected
- Credential: not provided
- Storage: not connected
- Telemetry: off
- Status: not installed and not executed

## Exact review states

`cover`, `host`, `capability`, `context`, `boundary`, `package`, `mobile`

## Boundary

No live installation, DOM scraping, hidden context collection, API, model call, credential, storage, telemetry, account access, host mutation, UX or backend is connected.

## Deterministic asset token

`easdk-v1-20260730`

## Implementation self-check

```bash
python3 tests/validate_reference.py
node --check scripts/review.js
python3 tests/browser_self_check.py
```

These commands are implementation-owned checks. They are not independent `LOCAL_VALIDATION_PASS` and do not establish `UI_APPROVED`.
