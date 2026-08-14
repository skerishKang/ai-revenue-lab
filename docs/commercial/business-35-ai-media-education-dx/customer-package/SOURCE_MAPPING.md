# SOURCE_MAPPING — Business 35 Customer Package

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
PRE_V3_1_GENERATED_ARTIFACTS=HISTORICAL_ONLY
PROVIDER=파디엠
CONTRACTING_ENTITY=파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

This mapping distinguishes **current product authority** from the **historical source snapshot used to generate the existing binaries**. Those are not the same thing.

## Current product authority

```text
Product: 파디엠 AI 미디어 업무전환 스튜디오
Merged product PR: #370
Merged product commit: 05932da3af774220372f0e9f3716b07cd83511f9
Product contract: reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
Commercial bridge: ../CURRENT_PRODUCT_AUTHORITY.md
```

Current product journey:

```text
현재 미디어 업무 병목 이해
→ 조직·결과물·병목·팀 규모·AI 사용 상태 입력
→ 조직별 진단 + 새 업무 흐름 + 추천 파일럿 확인
→ 운영체계 산출물 이해
→ 진단 워크숍 또는 6주 파일럿 범위 판단
→ 자기 조직용 전환 요약으로 상담 준비
```

A future customer package must lead with this current journey. A seven-step education/delivery sequence may appear only as downstream execution detail.

## Historical generation authority for current binaries

The existing PPTX/PDF/DOCX/XLSX and rendered PNGs were generated before V3.1 product acceptance from the earlier sales-kit snapshot:

```text
Historical sales-kit PR: #355
Historical source head used by current binaries: 8ae294d865fd10f9b23ff1388c5a4e79fb440b18
Historical authority docs:
  01-one-page-offer.md
  02-ten-page-proposal.md
  03-diagnostic-questionnaire.md
  04-six-week-pilot-plan.md
  05-statement-of-work-draft.md
  06-risk-and-data-annex.md
  07-kpi-measurement-framework.md
  08-customer-qualification-scorecard.md
  SOURCES.md
```

Therefore:

```text
EXISTING_GENERATED_BINARY_PRODUCT_AUTHORITY=PRE_V3_1
EXISTING_GENERATED_BINARY_SEND_STATUS=STALE
DO_NOT_RELABEL_OLD_BINARY_AS_V3_1
```

## Historical proposal deck mapping

The current binary `Business35_Master_Proposal_10p` maps to the pre-V3.1 source as follows:

```text
Slide 1  → historical proposal cover/current-problem framing
Slide 2  → historical current-problem / education-limit framing
Slide 3  → historical seven-step Business 35 method
Slide 4  → historical diagnosis / synthetic work examples
Slide 5  → historical Offer A
Slide 6  → historical Offer B
Slide 7  → historical Week 0–6 delivery plan
Slide 8  → historical KPI + risk/data annex
Slide 9  → price-hypothesis ladder
Slide 10 → historical next action
```

This mapping remains useful for provenance, **not** for claiming that the binary represents the accepted V3.1 product.

## Historical one-page / questionnaire / quote mapping

```text
Business35_OnePage_Offer
  → historical 01-one-page-offer.md

Business35_Diagnostic_Questionnaire
  → historical 03-diagnostic-questionnaire.md + Issue #353 structure

Business35_Pilot_Quote_Template
  → historical A/B/C pricing contract + pilot assumptions
  → SOW payment terms are legal-review-only source material
```

## Required mapping for next regeneration

The regenerated package must show both current product and commercial continuity:

```text
Proposal / one-page product identity
  → CURRENT_PRODUCT_AUTHORITY.md
  → reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md

Diagnosis / workflow / pilot story
  → V3.1 primary journey
  + updated 03-diagnostic-questionnaire.md
  + updated 04-six-week-pilot-plan.md

A/B1/B2/C offers and price hypotheses
  → updated commercial README / offer sources

KPI / risk / data / legal boundaries
  → updated 06-risk-and-data-annex.md
  + 07-kpi-measurement-framework.md
  + professional legal/contract review where required
```

## Legal-review-only linkage

```text
SOW (05) / risk-data annex (06): not customer-submission documents before review.
They may be source references only while LEGAL_REVIEW_REQUIRED remains true.
```

## Send gate

A source-map validator passing against the old binaries is not sufficient. Before any send, this mapping must reference a **new regeneration head** and the regenerated artifacts must be reviewed against V3.1.

```text
V3_1_REGENERATED_ARTIFACT_HEAD=NOT_YET_CREATED
CURRENT_PRODUCT_ARTIFACT_MAPPING=PENDING
CUSTOMER_SEND_READY=false
DO_NOT_SEND
```
