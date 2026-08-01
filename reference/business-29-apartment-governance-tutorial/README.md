# Business 29 — 공동주택 운영 단계별 가이드 (비식별 합성 튜토리얼)

Guided tutorial — de-identified synthetic, visual demo only.

## What this is

A step-by-step visual tutorial of apartment-community operation problem types,
**fully de-identified**. It is a synthetic visual guide, not real data, not a
legal tool, and not a product backend.

```text
synthetic only       — 모든 단지명·인물·날짜·금액·사건·소송·고소·CCTV·투표 결과는 합성
visual demo only     — no backend, database, authentication, or deployment
no legal judgement   — 판정을 내리지 않으며 안내 표현만 사용
guide vocabulary     — 확인 필요 · 자료 부족 · 절차 보완 필요 · 공개 보류 · 전문 검토 필요 · 기록 유지
```

## Fixture

```text
Community:  솔빛마루 2단지 (합성) · 420세대
Roles:      합성 관리자 · 동대표 · 선관위원 · 관리사무소 · 외부 검토자 · 일반 주민
```

## Chapters (7)

```text
1. 회의 준비와 사전 공고
2. 역할·권한·이해관계 확인
3. 출석과 정족수
4. 소명자료와 반대 의견
5. 의결과 후속조치
6. 주민 공개·가림처리·공개 보류
7. 변경이력과 감사기록
```

## Scenarios (7)

```text
정상 회의 · 정족수 미달 · 소명자료 누락 · 이해관계 확인 필요 · 반대 의견 존재 ·
주민 공개 보류 · 기한초과 후속조치
```

## Run

```bash
# repository-local tests (no browser)
node reference/business-29-apartment-governance-tutorial/tests/validate_tutorial.test.js

# headless browser validation (desktop/tablet/mobile/console/network)
# requires `npm install playwright` (browsers reused from cache)
NODE_PATH=<playwright node_modules> node reference/business-29-apartment-governance-tutorial/tests/browser_check.js
```

Browser validation result: **PASS** (desktop 1440x900 · tablet 768x1024 · mobile 390x844 —
0 console errors · 0 page errors · 0 failed requests · 0 external network requests).

Evidence: `evidence/browser-check.json`, `evidence/self-check.json`

## Boundary

No backend, database, authentication, deployment, real data, real voting, legal
judgement, CCTV, or real litigation material. Static HTML/CSS/JS only, all local.
