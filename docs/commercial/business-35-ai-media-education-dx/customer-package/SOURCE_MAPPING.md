# SOURCE_MAPPING — Business 35 Customer Package

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
CURRENT_REGENERATED_PACKAGE_SOURCE = 63adbefcf24a91a5a064c6b8e13779e151ba7de7
CURRENT_REGENERATED_PACKAGE_PRODUCT_AUTHORITY = 05932da3af774220372f0e9f3716b07cd83511f9
CURRENT_BINARY_STATUS = V3_1_REGENERATED_FROM_ACCEPTED_SOURCE
PROVIDER=파디엠
CONTRACTING_ENTITY=파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

This mapping distinguishes **current product authority** from the **historical
source snapshot that produced the pre-V3.1 binaries**. Those are not the same thing.

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

The regenerated customer package leads with this current journey. A seven-step
education/delivery sequence appears only as downstream execution detail.

## Current regenerated package (V3.1, final Lane B)

The PPTX/PDF/DOCX/XLSX and rendered PNGs in this directory were regenerated
from the exact accepted Lane A source revision by the recorded generator commit:

```text
CURRENT_REGENERATED_PACKAGE_SOURCE=63adbefcf24a91a5a064c6b8e13779e151ba7de7
CURRENT_REGENERATED_PACKAGE_PRODUCT_AUTHORITY=05932da3af774220372f0e9f3716b07cd83511f9
CURRENT_BINARY_STATUS=V3_1_REGENERATED_FROM_ACCEPTED_SOURCE
Accepted Lane A documents consumed (read-only, via git show):
  CURRENT_PRODUCT_AUTHORITY.md
  README.md
  01-one-page-offer.md
  02-ten-page-proposal.md
  03-diagnostic-questionnaire.md
  04-six-week-pilot-plan.md
  05-statement-of-work-draft.md
  06-risk-and-data-annex.md
  07-kpi-measurement-framework.md
  08-customer-qualification-scorecard.md
  SOURCES.md
Generator: validation/ builders at the GENERATOR_REVISION recorded in
  GENERATION_MANIFEST.json (full 40-char commit SHA)
Trace: GENERATION_MANIFEST.json (SOURCE_REVISION / PRODUCT_AUTHORITY_REVISION /
  GENERATOR_REVISION / OUTPUT_FILE_LIST / OUTPUT_HASHES)
```

Therefore:

```text
CURRENT_GENERATED_BINARY_PRODUCT_AUTHORITY=V3_1_ACCEPTED_SOURCE
CURRENT_GENERATED_BINARY_SEND_STATUS=NOT_READY_FOR_SEND
W4_PIXEL_REVIEW=AWAITING_W4
DO_NOT_SEND_UNTIL_W4_BUSINESS_LEGAL_PRICE_GATES_COMPLETE
```

## Current proposal deck mapping (V3.1 regenerated)

The regenerated binary `Business35_Master_Proposal_10p` maps to the accepted
V3.1 source (02-ten-page-proposal.md) as follows:

```text
Slide 1  → V3.1 Page 1 제품과 결과 (product spine + six-stage journey)
Slide 2  → V3.1 Page 2 지금 바꿀 업무를 고른다 (five inputs)
Slide 3  → V3.1 Page 3 조직별 진단이 나온다
Slide 4  → V3.1 Page 4 새 업무 흐름을 설계한다 (Before/After, human gates)
Slide 5  → V3.1 Page 5 운영 산출물을 확인한다 (8 artifacts)
Slide 6  → V3.1 Page 6 상품 A · 진단 워크숍
Slide 7  → V3.1 Page 7 상품 B1/B2 · 6주 파일럿 (delivery detail only)
Slide 8  → V3.1 Page 8 KPI와 위험을 함께 본다
Slide 9  → V3.1 Page 9 상품 C와 가격 가설
Slide 10 → V3.1 Page 10 다음 행동과 계약 경계
```

Slide 4 is the Before/After workflow with human approval gates; it does not
define a seven-step education sequence as the product identity. The Week 0–6
structure on Slide 7 is downstream delivery detail.

## Current one-page / questionnaire / quote mapping (V3.1 regenerated)

```text
Business35_OnePage_Offer
  → accepted 01-one-page-offer.md (six user steps, A/B1/B2/C hypotheses)

Business35_Diagnostic_Questionnaire
  → accepted 03-diagnostic-questionnaire.md
  → Q1 조직 유형 / Q2 결과물 유형 / Q3 병목 지점 / Q4 현재 팀 규모 / Q5 AI 사용 상태 (fillable)
  → Q6–Q17 flow/baseline/governance/readiness detail

Business35_Pilot_Quote_Template
  → accepted 01 offer/price hypotheses (A/B1/B2/C + VAT rule)
  → SOW payment terms are legal-review-only source material
```

## Historical lineage (provenance only, not current)

The pre-V3.1 package built in PR #359 (generator lineage
ef343f420661cda5f86cc2848404bca8f1dffe54) from the earlier sales-kit
snapshot (historical sales-kit PR: #355, source head
8ae294d865fd10f9b23ff1388c5a4e79fb440b18) remains preserved in Git history
for provenance. Its historical slide mapping was:

```text
Historical Slide 1  → historical proposal cover/current-problem framing
Historical Slide 2  → historical current-problem / education-limit framing
Historical Slide 3  → historical seven-step Business 35 method
Historical Slide 4  → historical diagnosis / synthetic work examples
Historical Slide 5  → historical Offer A
Historical Slide 6  → historical Offer B
Historical Slide 7  → historical Week 0–6 delivery plan
Historical Slide 8  → historical KPI + risk/data annex
Historical Slide 9  → price-hypothesis ladder
Historical Slide 10 → historical next action
```

This historical mapping is provenance only and must not be read as the
current V3.1 product mapping above.

```text
EXISTING_PRE_V3_1_BINARY_PRODUCT_AUTHORITY=PRE_V3_1
EXISTING_PRE_V3_1_BINARY_SEND_STATUS=STALE
DO_NOT_RELABEL_OLD_BINARY_AS_V3_1
```

## Required mapping for next regeneration

The regenerated package shows both current product and commercial continuity:

```text
Proposal / one-page product identity
  → CURRENT_PRODUCT_AUTHORITY.md
  → reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md

Diagnosis / workflow / pilot story
  → V3.1 primary journey
  + accepted 03-diagnostic-questionnaire.md
  + accepted 04-six-week-pilot-plan.md

A/B1/B2/C offers and price hypotheses
  → accepted commercial README / offer sources

KPI / risk / data / legal boundaries
  → accepted 06-risk-and-data-annex.md
  + 07-kpi-measurement-framework.md
  + professional legal/contract review where required
```

## Legal-review-only linkage

```text
SOW (05) / risk-data annex (06): not customer-submission documents before review.
They may be source references only while LEGAL_REVIEW_REQUIRED remains true.
```

## Send gate

```text
V3_1_REGENERATED_ARTIFACT_HEAD=see GENERATION_MANIFEST.json BASE_SHA
CURRENT_PRODUCT_ARTIFACT_MAPPING=V3_1_REGENERATED_FROM_ACCEPTED_SOURCE
W4_PIXEL_REVIEW=AWAITING_W4
CUSTOMER_SEND_READY=false
DO_NOT_SEND
```
