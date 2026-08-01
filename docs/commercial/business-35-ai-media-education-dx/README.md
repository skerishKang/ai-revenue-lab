# Business 35 · AI Media Education & DX — Commercial Sales Kit Drafts

```
INTERNAL COMMERCIAL DRAFT
OWNER APPROVAL REQUIRED
NOT YET SENT TO A CUSTOMER
```

Repository-local commercial draft source for the Business 35 sales kit and first paid pilot contract package. This is **not** a customer-facing final design file and **not** a legally reviewed contract.

- Product decision: Issue #253
- Phase 1 visual contract: Issue #255
- UI PR: #257 · MERGED at `ff61e3be6aef2ca7855a78b4c7c6249225d5be78`
- Commercial decision: Issue #350
- Sales package contract: Issue #353
- Production: https://ai-revenue-business-35-ai-media-education-dx.pages.dev/
- Current state: `UI_DEPLOYED_VERIFIED` · `COMMERCIAL_OFFER_DEFINED` · `UX_NOT_STARTED` · `BACKEND_FROZEN`

## Scope

This directory is the only allowed scope for this sales kit work:

```text
docs/commercial/business-35-ai-media-education-dx/**
```

Everything outside this path is prohibited to modify.

## Documents

| File | Content | Status |
|---|---|---|
| `01-one-page-offer.md` | 1-page offer | INTERNAL COMMERCIAL DRAFT |
| `02-ten-page-proposal.md` | 10-page proposal source | INTERNAL COMMERCIAL DRAFT |
| `03-diagnostic-questionnaire.md` | Customer diagnostic questionnaire | INTERNAL COMMERCIAL DRAFT |
| `04-six-week-pilot-plan.md` | 6-week pilot delivery plan | INTERNAL COMMERCIAL DRAFT |
| `05-statement-of-work-draft.md` | Statement of Work draft | DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED |
| `06-risk-and-data-annex.md` | Risk and data handling annex | DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED |
| `07-kpi-measurement-framework.md` | KPI measurement framework | INTERNAL COMMERCIAL DRAFT |
| `08-customer-qualification-scorecard.md` | Customer qualification scorecard | INTERNAL COMMERCIAL DRAFT |
| `SOURCES.md` | Legal/policy/market source register | — |
| `tests/validate_sales_package.py` | Validation script | — |

## Pricing contract

```text
상품 A · 진단 워크숍:
표준 300만–800만원
초기 제안 300만–500만원

상품 B · 디자인 파트너 파일럿:
1,000만–1,500만원

상품 B · 표준 6주 파일럿:
1,500만–2,500만원

상품 C · 조직 운영 자문:
월 300만–600만원
```

```text
가격은 시장 검증 전 가설
실제 견적은 범위 확인 후 별도 승인
VAT 별도 여부는 최종 견적 시 명시
실제 계약·매출 발생 주장 아님
```

## Trust boundaries

- Forbidden expression: the claim that AI adoption is mandated for organizations (강제 도입 주장). Use instead: `AI 활용 확산과 함께 개인정보·저작권·투명성·안전성·사람 검토 등 조직 차원의 사용정책과 거버넌스 요구가 강화되고 있다.`
- Public procurement: only "추정가격 2천만원 이하 소액 용역 가능성 검토" and "실제 계약방식은 기관 계약담당자 확인 필요". No automatic ≤ ₩100M negotiated-contract claim.
- SOW and legal/data documents: `DRAFT · PROFESSIONAL LEGAL REVIEW REQUIRED`.
- All pricing is a pre-market-validation hypothesis; it is not an actual contract or revenue claim.

## Validation

```bash
python3 docs/commercial/business-35-ai-media-education-dx/tests/validate_sales_package.py
```

### Validator scope

```text
Validator verifies:
repository structure
source status declarations
customer-document source linkage
forbidden claims
price consistency
required legal-review labels

Validator does not independently prove:
external URL availability
source authenticity
legal interpretation
market validity
customer suitability
```

`ALL CHECKS PASSED` does not mean every external fact has been independently verified at runtime.

## Non-actions

No customer outreach, email, proposal submission, real customer names, pricing negotiation, contract signing, claimed legal review, PPTX/Canva final design, UI/UX/backend change, Cloudflare change, PR Ready, merge, or Issue closure.
