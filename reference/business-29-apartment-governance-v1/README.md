# Proposed Business 29 — Apartment Governance / 우리단지 운영실

Phase 1 `UI_ONLY` visual reference for Issue #237.

## Promise

공동주택의 회의, 규정, 공고, 지출, 계약, 선거, 민원, 의결과 공개·비공개 기록을 주민이 이해할 수 있는 하나의 운영 이력으로 연결한다.

## Fixture

Every person, committee, vendor, amount, vote, record and image is synthetic. The only community represented is fictional `솔빛마루 2단지 / Solbit Maru 2` (420 households), 2026 Q3.

## Review states

`cover`, `meeting`, `rules`, `spending`, `election`, `complaint`, `mobile`.

## Boundary

No real data, voting, payment, procurement, accounting, signature, submission, OCR, transcription, legal judgement, authentication, persistence, notification, UX acceptance, backend or deployment.

## Self-check

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```

Browser results are implementation self-check evidence only and do not replace independent Local validation.
