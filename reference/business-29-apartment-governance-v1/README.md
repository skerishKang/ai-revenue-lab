# Business 29 — 방림명지로드힐 우리단지 운영실 / Apartment Governance

Phase 1 `UI_ONLY` visual reference for Issue #237 — **방림명지로드힐 운영 데모** (실제 단지 적용형 시연).

## Promise

방림명지로드힐의 회의, 규약, 공고, 의결, 민원, 지출, 후속조치와 주민 공개 기록을 하나의 운영 이력으로 연결합니다.

## Identity (authorized)

```text
Apartment:  방림명지로드힐아파트 (Bangnim Myeongji Roadhill Apartment)
Region:     광주광역시 남구
Buildings:  101동 · 102동
Households: 192세대
Council:    제5기 입주자대표회의
Chair:      회장 김경애
```

단지명과 운영 주체 정보는 입주자대표회의 회장 측 승인에 따라 사용합니다. 데모용 문서·예시 값은 실제 확정 자료가 아닙니다.

## Review states

`cover`, `meeting`, `rules`, `spending`, `election`, `complaint`, `mobile`.

## Boundary

```text
방림명지로드힐 운영 데모   — real-complex identity applied (authorized)
실제 단지 적용형 시연       — visual reference for resident/council review
개인정보 포함 자료는 공개 전 검토·가림처리
회의·공개·의결은 담당자 확인 후 확정
전자투표·계약·결제 기능은 현재 데모 범위 아님
데모 예시 / 작성 예시 / 검토 전 초안  — 데모용 문서·예시 값은 실제 확정 자료가 아님
No real voting, payment, procurement, contract execution, OCR, legal judgement,
authentication, persistence, notification, UX acceptance, backend or deployment.
```

## Self-check

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
node tests/validate.mjs   # requires a static server on port 8001 + Playwright
```

Browser results are implementation self-check evidence only and do not replace independent Local validation.
