# Business 35 · 파디엠 AI 미디어 업무전환 스튜디오 — Customer Package

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
PRE_V3_1_GENERATED_ARTIFACTS=STALE_FOR_SEND
PROVIDER=파디엠
CONTRACTING_ENTITY=파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
DO_NOT_MERGE
```

This branch contains the existing Business 35 customer-package build system and historical generated artifacts. It is **not** currently customer-send-ready.

The product source of truth changed after these binaries were generated: merged PR #370 established **파디엠 AI 미디어 업무전환 스튜디오** as the accepted V3.1 product direction. See `../CURRENT_PRODUCT_AUTHORITY.md` and `reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md`.

## Current product contract

The customer story must now follow the V3 product promise:

> AI 교육을 듣는 데서 끝내지 않고, 팀의 실제 미디어 업무 한 흐름을 사람이 승인하는 운영체계로 바꾼다.

Primary product journey:

```text
현재 미디어 업무 병목 이해
→ 조직·결과물·병목·팀 규모·AI 사용 상태 입력
→ 조직별 진단 + 새 업무 흐름 + 추천 파일럿 확인
→ 운영체계 산출물 이해
→ 진단 워크숍 또는 6주 파일럿 범위 판단
→ 자기 조직용 전환 요약으로 상담 준비
```

The old seven-step education/consulting narrative may remain as a **delivery-plan detail**, but it may no longer define the product identity or lead the proposal.

## Current customer segment

```text
지역 문화기관
지역 교육기관
지역 협회·단체
지역 미디어·콘텐츠 기관
기업 홍보·콘텐츠팀
```

Public procurement is not a headline sales message.

## Provider identity

```text
제공 및 계약 주체: 파디엠 (영문 필요 시 PADIEM)
제품/서비스: 파디엠 AI 미디어 업무전환 스튜디오
```

`AI Revenue Lab`은 포트폴리오·내부 프로젝트 브랜드이며 고객-facing 계약 주체로 표시하지 않는다. 공식 로고 파일이 확인될 때까지 로고·심벌·워드마크는 새로 만들지 않는다.

사업자등록번호·대표자·주소·연락처·계좌는 미확인 상태다. 발송 전 공식 정보 입력이 필요하다.

## Existing files

```text
Business35_Master_Proposal_10p.pptx / .pdf
Business35_OnePage_Offer.pdf / Source.pptx
Business35_Diagnostic_Questionnaire.docx / .pdf
Business35_Pilot_Quote_Template.xlsx
Business35_Customer_Meeting_Script.md
Business35_Followup_Email_Templates.md
rendered/
xlsx-rendered/
validation/
```

These files remain useful as **historical pre-V3.1 build evidence**, but the generated customer artifacts must be regenerated after the V3.1 source/story/design reconciliation. Do not relabel old binaries as current by editing Markdown only.

## Commercial offer continuity

The current A/B1/B2/C ranges are hypotheses pending market validation:

```text
A  진단 워크숍 초기형 300만–500만원 / 확장형 500만–800만원
B1 디자인 파트너 1,000만–1,500만원
B2 표준 6주 파일럿 1,500만–2,500만원
C  운영 자문 월 300만–600만원
```

No actual customer price, contract, or revenue is claimed.

## Legal / fact boundaries

Forbidden customer claims include:

```text
AI 도입 의무
공공기관은 반드시 도입
법적으로 안전
저작권 문제 없음
개인정보 문제 없음
정부 지원금 수령 가능
1억원 이하 자동 수의계약
성과 보장
```

Use bounded language such as `조직별 사용정책과 검토체계가 필요`, `개인정보·저작권·조달은 고객별 확인 필요`, and `전문 법률·계약 검토 필요`.

SOW and risk/data annex remain legal-review-only sources and are not customer-submission documents before professional review.

## V3.1 visual continuity

The next regeneration must align with the accepted V3.1 product system:

```text
warm ivory field
+ dark forest typography
+ restrained cobalt information accents
+ calm institutional / educational tone
+ strong Korean hierarchy
+ no neon / robot / circuit cliché
```

The package does not need to copy the website pixel-for-pixel, but it must feel like the same product.

## Regeneration gate

Before any customer send:

1. rewrite proposal/one-page/customer scripts against `CURRENT_PRODUCT_AUTHORITY.md`;
2. regenerate PPTX/PDF/DOCX/XLSX from those updated sources;
3. rerun repository validator and formula checks;
4. rerender all pages/sheets;
5. perform fresh Web CTO pixel review after regeneration;
6. verify official Padiem business details;
7. complete required legal/contract review;
8. explicitly approve price hypothesis for the specific customer scope.

Until all eight are complete:

```text
CUSTOMER_SEND_READY=false
PRE_V3_1_GENERATED_ARTIFACTS=STALE_FOR_SEND
DO_NOT_SEND
DO_NOT_MERGE
```
