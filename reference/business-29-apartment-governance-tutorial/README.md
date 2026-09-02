# Business 29 — 방림명지로드힐 우리단지 운영실 (단계별 운영 가이드)

Guided tutorial — **실제 단지 적용형 시연** for 방림명지로드힐아파트.

## What this is

A step-by-step visual guide connecting the apartment complex's meeting, notice,
quorum, opinions, resolution, disclosure and audit records so residents can
understand the operation. It is a **방림명지로드힐 운영 데모**.

```text
방림명지로드힐 운영 데모   — real-complex identity applied (with user authorization)
실제 단지 적용형 시연       — visual demo for resident/council review
개인정보 포함 자료는 공개 전 검토·가림처리
회의·공개·의결은 담당자 확인 후 확정
전자투표·계약·결제 기능은 현재 데모 범위 아님
데모 예시 / 작성 예시 / 검토 전 초안  — 데모용 문서·예시 값은 실제 확정 자료가 아님
```

## Identity (authorized)

```text
Apartment:  방림명지로드힐아파트 (Bangnim Myeongji Roadhill Apartment)
Region:     광주광역시 남구
Buildings:  101동 · 102동
Households: 192세대
Council:    제5기 입주자대표회의
Chair:      회장 김경애
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

Roles used: 입주자대표회의 회장 · 동대표 · 감사 · 선거관리위원장 · 관리소장 ·
관리사무소 담당자 · 일반 주민 · 외부 검토자.

## Boundary

```text
no legal judgement      — 판정을 내리지 않으며 안내 표현만 사용
no real voting          — 전자투표 구현 없음 (데모 범위 아님)
no contract/payment     — 계약·결제 구현 없음 (데모 범위 아님)
no backend/db/auth      — static HTML/CSS/JS only
no real litigation data — 소송·고소·CCTV·투표 결과 데이터 사용하지 않음
```

## Run

```bash
# repository-local tests (no browser)
node reference/business-29-apartment-governance-tutorial/tests/validate_tutorial.test.js

# headless browser validation (desktop/tablet/mobile/console/network)
# requires `npm install playwright` (browsers reused from cache)
NODE_PATH=<playwright node_modules> node reference/business-29-apartment-governance-tutorial/tests/browser_check.js
```

Evidence: `evidence/browser-check.json`, `evidence/self-check.json`
