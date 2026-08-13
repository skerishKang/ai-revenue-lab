# Business 49 · Public Data Connector Hub — Phase 1 visual reference

Static, synthetic UI-only reference for a **Public Data Connector Workshop / 공공데이터 연결 작업장**.

## Product result

`HUMAN-REVIEWED PUBLIC DATA CONNECTOR SPEC`

## Synthetic datasets

- Morae City Ordinance Index
- Morae Open Statistics Table
- Morae Procurement Notices Feed

All agencies, URLs, schemas, licences, dates, records and validation results are fictional.

## Review states

`cover`, `catalog`, `source`, `schema`, `quality`, `package`, `mobile`

## Boundary

No live API, scraping, credentials, ingestion, storage, legal advice, official endorsement, UX or backend is connected.

## Deterministic asset token

`pdc-v1-20260729`

## Local checks

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```

Implementation self-check is not independent `LOCAL_VALIDATION_PASS`.
