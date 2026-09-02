# VISUAL_QA — Business 35 Customer Package (V3.1 Deterministic Build)

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
PRODUCT_CONTRACT=reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
GENERATOR_LINEAGE=PR #359 @ ef343f420661cda5f86cc2848404bca8f1dffe54
GENERATION_MANIFEST=GENERATION_MANIFEST.json
BUILD_MODE=DETERMINISTIC_REGENERATION
BASE_SHA=c6e0c610bf764006c9b32b73784aef7854f08cd0
```

## Generated artifacts under QA

```text
Business35_Master_Proposal_10p.pptx / .pdf (10 slides)
Business35_Master_Proposal_10p
Business35_OnePage_Offer_Source.pptx / Business35_OnePage_Offer.pdf (1 page)
Business35_OnePage_Offer
Business35_Diagnostic_Questionnaire.docx / .pdf (3 pages)
Business35_Diagnostic_Questionnaire
Business35_Pilot_Quote_Template.xlsx (9 sheets)
```

## Rendered evidence (deterministic placeholders for W4 pixel QA)

```text
rendered/proposal-01.png
rendered/proposal-02.png
rendered/proposal-03.png
rendered/proposal-04.png
rendered/proposal-05.png
rendered/proposal-06.png
rendered/proposal-07.png
rendered/proposal-08.png
rendered/proposal-09.png
rendered/proposal-10.png
rendered/onepage-1.png
rendered/questionnaire-1.png
rendered/questionnaire-2.png
rendered/questionnaire-3.png
xlsx-rendered/instructions.png
xlsx-rendered/customer-scope.png
xlsx-rendered/offer-a.png
xlsx-rendered/offer-b1.png
xlsx-rendered/offer-b2.png
xlsx-rendered/offer-c.png
xlsx-rendered/optional-items.png
xlsx-rendered/assumptions.png
xlsx-rendered/approval.png
```

Every rendered filename above is listed for traceability. Fresh headless render required for final W4 Web CTO pixel review.

## QA verdict (current deterministic build)

```text
BLOCKER: 0
MAJOR: 0
blocker_count: 0
major_count: 0
OVERLAP: 0
CLIPPING: 0
TEXT_OVERFLOW: 0
KOREAN_GLYPH: PASS
PRICE_LABEL: PASS
FOOTER: PASS
```

Geometry checks: no shape overflow, no text overlap (slides 3/4/8 verified), editable text/shapes, page numbers, speaker notes, 16:9.

## Notes

- This build recovers generation infrastructure from PR #359 and reconciles it to current main (Lane B parallel-safe). Historical pre-V3.1 binaries remain STALE_FOR_SEND.
- Final V3.1 customer binaries must be regenerated from accepted #1503 exact source revision; this manifest records PENDING_ACCEPTED_1503 until then.
- validator는 시각 검증을 대신하지 않는다. 이 검사는 구조/공식/매핑 검증이며, 실제 픽셀 가독성·계층·테이블·브랜드 연속성은 W4 Web CTO pixel review에서 별도로 확인해야 한다.
- Deterministic: fixed timestamps (2026-09-03), deterministic core properties, sorted output lists, Pillow/reportlab placeholders for evidence.

## Current disposition

```text
CURRENT_V3_1_ARTIFACTS=REGENERATED_DETERMINISTIC
CURRENT_V3_1_PIXEL_REVIEW=PENDING_W4
CUSTOMER_SEND_READY=false
DO_NOT_SEND
DRAFT
```
