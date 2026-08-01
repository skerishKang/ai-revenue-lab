# Business 30 · Civic AI Navigator

Phase 1 static visual reference for **시민 AI 내비게이터 / Civic AI Navigator**.

## Product promise

Connect a citizen's natural-language question to official-source markers, responsible office, procedure, preparation, exceptions, human-confirmation points and a non-submitted inquiry draft.

## Synthetic fixture

- Municipality: 해솔시 / Haesol City — fictional
- Office: 해솔시 시민생활안내과 — fictional
- Question: 부모님 이사 뒤 주소 변경과 생활요금 정리를 어디서부터 해야 하는가
- Freshness date: 2026-07-28 — synthetic UI date
- No real government data, advice, submission or connection

## Seven visual states

`cover`, `question`, `source-map`, `procedure`, `branches`, `draft`, `mobile`

## Run

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/`.

## Tests

```bash
python3 tests/validate_static.py
python3 tests/validate_browser.py
node --check scripts/review.js
```

Implementation browser results are self-check evidence only. They do not replace independent Local validation or authorize deployment.

## Phase boundary

```text
UI_ONLY
NOT_VALIDATED_BY_LOCAL
NOT_DEPLOYED_PENDING_UI_APPROVAL
UX_NOT_STARTED
BACKEND_FROZEN
```
