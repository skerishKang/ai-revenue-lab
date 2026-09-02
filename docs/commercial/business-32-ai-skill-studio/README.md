# Business 32 · AI Skill Studio — Commercial Pilot Package

검증된 B32 UX를 **backend 없는 서비스형 유료 파일럿**으로 판매하기 위한 상업
패키지입니다. 상품·가격·고객·산출물·판매 경계를 정의하며, backend 구현이나 실제
고객 접촉을 포함하지 않습니다.

## 상업화 우선순위

```text
Commercial priority 1: Business 35 · AI Media Education & DX
Commercial priority 2: Business 29 · Apartment Governance
Commercial priority 3: Business 32 · AI Skill Studio
```

## 판매 문장 (고정)

```text
조직의 실제 반복 업무 하나를
입력자료·단계·증거·검토·예외·승인 기준이 포함된
재사용 가능한 AI 업무 스킬로 전환합니다.
```

Primary commercial result:

```text
VERIFIED ORGANIZATIONAL AI SKILL PACKAGE
검증된 조직 AI 업무 스킬 패키지
```

## Authority

```text
Product decision: #246
Validated UX PR: #354 (OPEN / Draft / unmerged)
Validated product exact head: 73ec4718d0835248ab20d56bc68f3956536112b4
Pilot UX handoff: #357 / PR #358
Validated handoff exact head: 29068281998b7f1a59d76a95174807ffbf20cb38
Commercial issue: #362
```

## Contents

```text
README.md
01-commercial-positioning.md           — 포지셔닝·판매 경계·1차 고객군
02-offer-ladder.md                     — Offer A/B/C 래더
03-b35-to-b32-sales-funnel.md          — B35 고객 후속 판매 funnel
04-skill-conversion-sprint.md          — 업무 스킬 전환 스프린트
05-team-pilot-plan.md                  — 팀 스킬 라이브러리 파일럿
06-deliverable-spec.md                 — 검증된 조직 스킬 패키지 명세
07-pricing-hypotheses.md               — 가격 가설과 산정 기준
08-customer-qualification-scorecard.md — 고객 우선순위 점수표
09-sales-meeting-script.md             — 30분 상담 대본
10-risk-data-and-authority-boundary.md — 리스크·데이터·권한 경계
11-pilot-acceptance-checklist.md       — 파일럿 승인 체크리스트
12-case-study-template.md              — 합성 사례 템플릿
tests/validate_commercial_package.py   — 패키지 검증기
```

## 상품 형태

```text
SERVICE-LED FRONTEND PILOT
```

현재 제공하지 않는 기능 (판매 금지):

```text
account · authentication · persistent database · live AI model
file upload · enterprise integration · billing · production automation
```

파일럿에서는 진행자가 검증된 frontend와 문서 템플릿을 사용해 결과를 납품합니다.

## 상태

```text
COMMERCIAL_PILOT_PACKAGE_REVIEW_READY
SERVICE_LED_FRONTEND_PILOT
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

모든 예시·사례는 합성입니다. 실제 고객, 실제 견적서, 실제 내부 문서는 사용하지
않습니다.

## 검증

```bash
python3 tests/validate_commercial_package.py
```
