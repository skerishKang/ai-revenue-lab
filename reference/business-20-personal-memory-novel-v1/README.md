# Proposed Business 20 — Personal Memory Novel

Phase 1 static visual UI reference for **Personal Memory Novel / 나의 기억소설**.

## Visual concept

**Memory Manuscript / 기억의 원고** — an annotated private literary manuscript in which source memory, factual anchors, inference, fictionalisation, redaction and final author approval remain visibly distinct.

## Status

- Product: proposed Business 20
- Phase: `UI_ONLY`
- Review status: `UI_REVIEW_READY`
- UX: not implemented and not approved
- Backend: frozen
- Runtime: static, deterministic, synthetic fixtures only

## Seven review states

1. 기억소설 표지
2. 원래 기억
3. 장면 초고
4. 변형 지도
5. 두 개의 문장
6. 작가 검토본
7. 모바일 390px 장면 읽기

Use the review tabs or `?state=cover|source|draft|map|versions|proof|mobile`.

## Run locally

```bash
python3 -m http.server 4173 --directory reference/business-20-personal-memory-novel-v1
```

No build step, package install, external font, CDN, analytics, API, upload, persistence or AI request is used.

## Validation

```bash
python3 reference/business-20-personal-memory-novel-v1/tests/validate_reference.py
python3 reference/business-20-personal-memory-novel-v1/tests/browser_validate.py
```

The browser validator requires Python Playwright and a local Chromium executable. Evidence is written under `evidence/`.
