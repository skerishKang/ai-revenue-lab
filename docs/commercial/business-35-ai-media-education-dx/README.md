# Business 35 · 파디엠 AI 미디어 업무전환 스튜디오 — Commercial Source Drafts

```text
INTERNAL COMMERCIAL DRAFT
OWNER APPROVAL REQUIRED FOR CUSTOMER SEND
NOT YET SENT TO A CUSTOMER
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
DO_NOT_MERGE
```

Repository-local commercial source package for Business 35. This directory is **not** a customer-facing final package and is **not** a legally reviewed contract.

## Current product authority

The historical Phase 1 UI/commercial source is no longer the product authority. Current product truth is:

```text
Product: 파디엠 AI 미디어 업무전환 스튜디오
Product reference: reference/business-35-ai-media-education-dx-v3/
Product contract: reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
V3.1 accepted/merged PR: #370
V3.1 merged commit: 05932da3af774220372f0e9f3716b07cd83511f9
CTO delegated direction: ACCEPT_V3_1_DIRECTION
```

See `CURRENT_PRODUCT_AUTHORITY.md` before editing any commercial document.

Current product state:

```text
V3_1_PRODUCT_REFERENCE=MERGED_TO_MAIN
SERVICE_LED_INTERACTIVE_STUDIO=ACCEPTED
COMMERCIAL_SOURCE_RECONCILIATION=IN_PROGRESS
CUSTOMER_PACKAGE_REGENERATION=PENDING
BACKEND_NOT_REQUIRED_FOR_THIS_DOC_SLICE
CUSTOMER_SEND_READY=false
```

Do not use historical `UI_DEPLOYED_VERIFIED / UX_NOT_STARTED` language as current product truth.

## Current product promise

> AI 교육을 듣는 데서 끝내지 않고, 팀의 실제 미디어 업무 한 흐름을 사람이 승인하는 운영체계로 바꾼다.

The commercial package must lead with the product journey:

```text
현재 미디어 업무 병목 이해
→ 조직·결과물·병목·팀 규모·AI 사용 상태 입력
→ 조직별 진단 + 새 업무 흐름 + 추천 파일럿 확인
→ 운영체계 산출물 이해
→ 진단 워크숍 또는 6주 파일럿 범위 판단
→ 자기 조직용 전환 요약으로 상담 준비
```

A seven-step education/delivery sequence may be used inside the delivery plan, but it may not define Business 35 as a generic training/consulting product.

## Scope

```text
docs/commercial/business-35-ai-media-education-dx/**
```

## Documents

| File | Content | Current status |
|---|---|---|
| `CURRENT_PRODUCT_AUTHORITY.md` | V3.1 commercial/product bridge | CURRENT AUTHORITY |
| `01-one-page-offer.md` | 1-page source | V3.1 RECONCILIATION REQUIRED/IN PROGRESS |
| `02-ten-page-proposal.md` | 10-page proposal source | V3.1 RECONCILIATION REQUIRED/IN PROGRESS |
| `03-diagnostic-questionnaire.md` | Customer diagnostic questionnaire | RECONCILE TO V3 INPUT MODEL |
| `04-six-week-pilot-plan.md` | 6-week pilot delivery plan | DELIVERY DETAIL; KEEP BOUNDED |
| `05-statement-of-work-draft.md` | Statement of Work draft | PROFESSIONAL LEGAL REVIEW REQUIRED |
| `06-risk-and-data-annex.md` | Risk/data handling annex | PROFESSIONAL LEGAL REVIEW REQUIRED |
| `07-kpi-measurement-framework.md` | KPI measurement framework | INTERNAL COMMERCIAL DRAFT |
| `08-customer-qualification-scorecard.md` | Customer qualification scorecard | INTERNAL COMMERCIAL DRAFT |
| `SOURCES.md` | Legal/policy/market source register | SOURCE REGISTER |
| `tests/validate_sales_package.py` | Legacy commercial consistency validator | MUST NOT BE READ AS PRODUCT ACCEPTANCE |

## Commercial offers / pricing hypotheses

```text
A · 진단 워크숍
  초기형 300만–500만원
  확장형 500만–800만원
  historical broad range token: 300만–800만원

B1 · 디자인 파트너 6주 파일럿
  1,000만–1,500만원

B2 · 표준 6주 파일럿
  1,500만–2,500만원

C · 조직 운영 자문
  월 300만–600만원
```

```text
가격은 시장 검증 전 가설
실제 견적은 고객 범위 확인 후 별도 승인
VAT 별도 여부는 최종 견적 시 명시
실제 계약·매출 발생 주장 아님
```

The primary next action is **진단 워크숍 또는 6주 파일럿 범위 확인**.

## Trust boundaries

- Do not claim AI adoption is legally mandatory.
- Use the bounded framing: `AI 활용 확산과 함께 개인정보·저작권·투명성·안전성·사람 검토 등 조직 차원의 사용정책과 거버넌스 요구가 강화되고 있다.`
- Public procurement terms require customer-specific confirmation; do not claim automatic negotiated-contract eligibility.
- SOW and legal/data documents remain `DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED`.
- Prices are hypotheses; no actual customer price, contract, or revenue is claimed.
- No real customer name/logo/testimonial/performance claim may be invented.

## Customer-package relationship

PR #359 contains the old generated PPTX/PDF/DOCX/XLSX package. Those binaries were produced before V3.1 acceptance and are now explicitly:

```text
PRE_V3_1_GENERATED_ARTIFACTS=STALE_FOR_SEND
HISTORICAL_PIXEL_EVIDENCE=PRESERVED
V3_1_REGENERATION_REQUIRED=true
DO_NOT_SEND
```

Do not make them current by changing labels only. The next package must be regenerated from V3.1-aligned sources and reviewed again.

## Validation boundary

```bash
python3 docs/commercial/business-35-ai-media-education-dx/tests/validate_sales_package.py
```

The validator checks structural/commercial consistency. A green result does **not** independently prove current-product alignment, legal interpretation, source authenticity, market validity, visual quality, customer suitability, or send readiness.

## Non-actions

No customer outreach, email/proposal submission, real customer data, pricing negotiation, contract signing, legal-review claim, Production/Cloudflare change, or customer-send approval is performed by this source reconciliation.
