# Business 35 · AI Media Education & DX — Customer-Facing Master Package

```
FINAL_IDENTITY_DECIDED
PROVIDER: 파디엠
CONTRACTING_ENTITY: 파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

Repository-local visual master package for Business 35 customer consultations. Produced from the validated sales-kit source (`feat/business-35-sales-kit`, exact head `8ae294d865fd10f9b23ff1388c5a4e79fb440b18`). This is **not** a customer submission.

## Scope

```text
docs/commercial/business-35-ai-media-education-dx/customer-package/**
```

The source documents one level up are authority sources and are **not** modified by this package.

## Customer segment (first master)

```text
지역 문화기관
지역 교육기관
지역 협회·단체
지역 미디어·콘텐츠 기관
```

Public procurement is not a headline sales message. Focus problems:

```text
홍보·교육·콘텐츠 제작이 수작업
AI 도구 사용이 개인별로 분산
검토·승인 기준 부재
개인정보·저작권·사람 검토 위험
교육 후 실제 업무 변화 부족
```

## Provider identity

Customer-facing provider is decided:

```text
제공 및 계약 주체: 파디엠 (영문 필요 시 PADIEM)
서비스: Business 35 · AI Media Education & DX · AI 업무전환 프로그램
```

`AI Revenue Lab`은 포트폴리오·내부 프로젝트 브랜드이며 고객-facing 계약 주체로 표시하지 않는다. 공식 로고 파일이 확인될 때까지 로고·심벌·워드마크는 만들지 않고 텍스트로만 표시한다.

사업자등록번호·대표자·주소·연락처·계좌는 미확인 상태이며, 발송 전 공식 정보 입력이 필요하다:

```text
BUSINESS_DETAILS_VERIFICATION_PENDING
```

Bracket placeholders appear only in the small customization areas of the cover and footer, not in the middle of customer screens.

## Files

```text
README.md
CUSTOMIZATION_CHECKLIST.md
SOURCE_MAPPING.md

Business35_Master_Proposal_10p.pptx
Business35_Master_Proposal_10p.pdf

Business35_OnePage_Offer.pdf
Business35_OnePage_Offer_Source.pptx

Business35_Diagnostic_Questionnaire.docx
Business35_Diagnostic_Questionnaire.pdf

Business35_Pilot_Quote_Template.xlsx

Business35_Customer_Meeting_Script.md
Business35_Followup_Email_Templates.md

rendered/    (PDF page images for review)
validation/  (validation report)
```

SOW (`05-statement-of-work-draft.md`) and the risk/data annex (`06-risk-and-data-annex.md`) are **not** converted to customer submission versions before legal review. This package links to the source documents and states the legal-review status only.

## Fact and source boundaries

- Forbidden numbers in customer visuals: `48.8%`, `28.7%`.
- SPRI `60.8%` is 2023 data and is omitted by default in these visuals; if ever used, survey year, survey scope, source, and the "not current as of 2026" limit must be shown on the same page.
- Prefer no statistics: persuade with the customer's actual diagnostic questions and workflow diagrams.
- No real customer names, logos, testimonials, or performance logos.

## Legal phrasing

Forbidden: `AI 도입 의무`, `공공기관은 반드시 도입`, `법적으로 안전`, `저작권 문제 없음`, `개인정보 문제 없음`, `정부 지원금 수령 가능`, `1억원 이하 자동 수의계약`, `성과 보장`.

Allowed: `조직별 사용정책과 검토체계가 필요`, `개인정보·저작권·조달은 고객별 확인 필요`, `전문 법률·계약 검토 필요`, `지원사업은 별도 공고 확인 필요`.

## Design direction

```text
한국 기관·기업 제안서
차분하고 신뢰감 있는 편집
넓은 여백
큰 한국어 제목
명확한 단계도
표와 숫자 최소화
AI 네온·로봇·회로 이미지 금지
```

No real customer logos, testimonials, or performance logos. No external stock images are downloaded. Repository-local shapes, lines, icons, and hand-built diagrams are used. No font files are added to the repository.

## Validation

```bash
python3 docs/commercial/business-35-ai-media-education-dx/customer-package/validation/validate_customer_package.py
git diff --check
```

PDF pages are rendered to images under `rendered/` for review; text overflow, clipped sentences, overlapping objects, broken Korean glyphs, page count, price consistency, unsourced numbers, real customer names, and performance claims are checked.

## Status

```text
FINAL_IDENTITY_DECIDED
PROVIDER: 파디엠
CONTRACTING_ENTITY: 파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
DO_NOT_MERGE
```

No customer outreach, email, proposal submission, pricing negotiation, contract, revenue claim, or deployment.
