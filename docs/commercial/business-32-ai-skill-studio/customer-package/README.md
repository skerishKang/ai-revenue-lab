# Business 32 · AI Skill Studio — Customer-Facing Pilot Package

검증된 상업 설계(PR #363)를 고객이 이해하고 검토할 수 있는 제안자료로 변환한
패키지입니다. **서비스형 프론트엔드 파일럿(SERVICE-LED FRONTEND PILOT)**이며
SaaS·자동화 플랫폼으로 판매하지 않습니다.

## 판매하는 것

```text
조직의 실제 반복업무 하나를
입력자료·단계·증거·검토·예외·승인 기준이 포함된
재사용 가능한 AI 업무 스킬로 전환하는 서비스
```

Primary result:

```text
VERIFIED ORGANIZATIONAL AI SKILL PACKAGE
검증된 조직 AI 업무 스킬 패키지
```

## Authority

```text
Commercial package PR: #363 (OPEN / Draft / unmerged)
Commercial package head: 30565f4ddcf99296751109df3a0973d7ba79eaa8
Validated UX PR: #354
Validated UX exact head: 73ec4718d0835248ab20d56bc68f3956536112b4
Pilot handoff PR: #358
Pilot handoff exact head: 29068281998b7f1a59d76a95174807ffbf20cb38
```

## 산출물

```text
README.md
SOURCE_MAPPING.md
CUSTOMIZATION_CHECKLIST.md
VISUAL_QA.md
Business32_Master_Proposal_10p.pptx / .pdf     — 10페이지 마스터 제안서
Business32_OnePage_Offer_Source.pptx / Business32_OnePage_Offer.pdf — 1페이지 원페이지 오퍼
Business32_Skill_Discovery_Worksheet.docx / .pdf — 업무 발견 워크시트(3페이지 이하)
Business32_Verified_Skill_Card_Sample.pptx / .pdf — 검증된 스킬 카드 샘플(2~3페이지)
Business32_Pilot_Quote_Template.xlsx           — 견적 템플릿(8시트)
Business32_Customer_Meeting_Script.md          — 고객 상담 대본
Business32_Followup_Email_Templates.md         — 후속 이메일 템플릿
rendered/                                      — PDF 페이지별 PNG 렌더
validation/                                    — 생성·검증 스크립트
```

## 생성 원칙

PPTX·PDF·DOCX·XLSX는 수동 편집하지 않습니다. `validation/` 아래 생성 스크립트로
제작합니다.

```text
validation/build_proposal_pptx.py
validation/build_one_page_pptx.py
validation/build_discovery_worksheet.py
validation/build_skill_card_pptx.py
validation/build_quote_xlsx.py
validation/validate_customer_package.py
```

## 고객용 정체성 (중립)

```text
Business 32 · AI Skill Studio
AI 업무 스킬 전환 프로그램
```

Padiem / New Green Korea / AI Revenue Lab 중 최종 제공자 정체성은 이번 단계에서
임의로 확정하지 않습니다.

## 시각 방향

```text
Skill Blueprint Workshop
업무 스킬 설계 도면
```

업무 흐름 도면·입력자료 태그·단계 번호·증거 영수증·검토 체크·예외 경고·승인
스탬프·버전 카드의 시각 문법을 사용합니다. 일반 SaaS 카드 벽, 챗봇 화면, 온라인
강의 사이트, 프롬프트 마켓, 코딩 IDE, 자동화 대시보드, 직원 평가표로 표현하지
않습니다.

## Footer 규칙

```text
표지:   DRAFT · 제공자 정보 최종 확정 필요
내부:   DRAFT
마지막: 가격 가설 · 제공자 정보 최종 확정 필요
```

모든 페이지에 긴 법률 문구를 반복하지 않습니다.

## 상태

```text
CUSTOMER_PACKAGE_STRUCTURALLY_VALIDATED
SERVICE_LED_FRONTEND_PILOT
PRICE_HYPOTHESIS_ONLY
PIXEL_VISUAL_QA_PENDING
FINAL_IDENTITY_REQUIRED
DO_NOT_SEND
```

## 검증

```bash
python3 validation/validate_customer_package.py
```

검증 항목: 제안서 10페이지, 원페이지 1페이지, 워크시트 3페이지 이하, 스킬 카드
2~3페이지, 렌더 PNG가 모든 PDF 페이지와 일치, 외부 런타임 0, 실제 고객·기관
데이터 0, backend·SaaS·자동승인 주장 0, 가격 가설 표시, 사람 검토 문구 필수.

## 금지

```text
실제 고객 접촉 · 제안서 발송 · 계약 · 매출 주장 · 가격 확정
backend · account · auth · database · live AI · file upload
enterprise integration · billing · production automation
PR #354 / #358 / #363 수정 · Ready · merge · Cloudflare
```
