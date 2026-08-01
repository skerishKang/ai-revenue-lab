# Business 32 · AI Skill Studio / AI 업무 실습실

Phase 1 `UI_ONLY` static visual reference for Issue #248.

## Product result

`VERIFIED ORGANIZATIONAL AI SKILL`

One bounded synthetic work task is executed through visible steps, linked to evidence, corrected by a fictional human reviewer, and represented as a reusable organizational skill. This reference performs no live execution, upload, model call, storage, submission, account, API, database, or enterprise integration.

## States

`cover`, `brief`, `guided-run`, `evidence`, `review`, `skill-card`, `mobile`

## Run

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/` from this workspace.

## Checks

```bash
python3 tests/validate_static.py
python3 tests/validate_browser.py
node --check scripts/review.js
```

Asset version token: `20260729-b32-1`.

## Boundary

All organizations, suppliers, quotations, prices, records and reviewer actions are synthetic. This is a visual reference, not accepted UX or a production system.
