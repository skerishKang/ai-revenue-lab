# Business 31 · Public Procedure Experience Data

Phase 1 `UI_ONLY` visual reference for **공공절차 경험 데이터**.

- Stable slug: `public-procedure-experience-data`
- Visual direction: `Procedure Field Atlas / 절차 현장 지도`
- Fixture: fictional `해솔시` synthetic procedure only
- State keys: `cover`, `procedure`, `citizen`, `staff`, `evidence`, `improvement`, `mobile`

## Run

```bash
python -m http.server 8000
# open http://localhost:8000
```

## Self-check

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
git diff --check
```

Implementation self-check does not constitute independent `LOCAL_VALIDATION_PASS`, Web CTO approval, UX approval, backend authorization, or deployment authority.
