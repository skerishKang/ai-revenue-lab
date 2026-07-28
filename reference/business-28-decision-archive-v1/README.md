# Business 28 · Decision Archive

Phase 1 `UI_ONLY` visual reference for **회의·결정 기록실 / Decision Archive**.

## Product promise

회의, 선택지, 이유, 반대 의견, 가정, 담당자, 기한, 후속 증거와 재검토 조건을 연결하여 “무엇을 왜 결정했는가”를 장기적으로 보존한다.

## Fixture

- Organization: 파도식탁 연구소 / Pado Table Lab — fictional
- Decision date: 2026-07-14 — synthetic
- Decision: 제한 지역에서 3주 파일럿 후 전국 확대 여부 재검토
- Owner: 윤서진 — fictional
- Revisit trigger: 파손률 1.8% 초과 또는 냉장 유지 실패 3건 이상

모든 인물, 조직, 날짜, 수치, 발언, 문서, 도장과 결과는 합성이다.

## Seven states

`cover`, `index`, `dossier`, `rationale`, `dissent`, `followup`, `mobile`

## Run

```bash
cd reference/business-28-decision-archive-v1
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/`.

## Checks

```bash
python tests/validate_static.py
node --check scripts/review.js
python tests/validate_browser.py
```

Browser validation is implementation self-check evidence, not independent Local Validator approval.

## Phase boundary

No upload, recording, OCR, transcription, AI summary, search, persistence, authentication, integrations, analytics, accepted UX, backend or production workflow exists.
