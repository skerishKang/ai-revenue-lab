# VISUAL_QA — Business 35 Customer Package (V3.1 Regenerated Render Log)

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
PRODUCT_CONTRACT=reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
SOURCE_REVISION=63adbefcf24a91a5a064c6b8e13779e151ba7de7
PRODUCT_AUTHORITY_REVISION=05932da3af774220372f0e9f3716b07cd83511f9
GENERATION_MANIFEST=GENERATION_MANIFEST.json
BUILD_MODE=DETERMINISTIC_REGENERATION_FROM_ACCEPTED_SOURCE
RENDER_MODE=REAL_RENDER_ONLY
```

## Generated artifacts under render (Lane B scope: generation only)

```text
Business35_Master_Proposal_10p.pptx / .pdf (10 slides)
Business35_Master_Proposal_10p
Business35_OnePage_Offer_Source.pptx / Business35_OnePage_Offer.pdf (1 page)
Business35_OnePage_Offer
Business35_Diagnostic_Questionnaire.docx / .pdf (3 pages)
Business35_Diagnostic_Questionnaire
Business35_Pilot_Quote_Template.xlsx (9 sheets)
```

## Rendered evidence (real renders from the final artifacts)

Customer PDFs are real native-engine exports (Microsoft PowerPoint COM for
proposal/one-page, Microsoft Word COM for questionnaire; LibreOffice headless
accepted where COM is unavailable) — no recomposed fallback PDFs. PDF pages
rasterized with PyMuPDF (real PDF rendering, deterministic scale); proposal
and one-page preserve the 16:9 PPTX slide geometry. XLSX sheets are exported
by Microsoft Excel COM (FitToPages 1x1, in-memory, source workbook unmutated;
LibreOffice Calc headless accepted where COM is unavailable), preserving
merges, fills, fonts, borders, column widths, row heights, conditional
formatting, and print areas — no recreated Pillow tables.
Renderer provenance (DOCUMENT_EXPORTER / XLSX_EXPORTER / REAL_* PASS) is
recorded in GENERATION_MANIFEST.json.
No synthetic placeholders are used. When no real renderer is available the
build fails with REAL_RENDER_EVIDENCE=UNAVAILABLE_BLOCKING instead of
generating placeholder evidence.

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

Every rendered filename above is listed for traceability and matches the
actual files produced by validation/render_artifacts.py.

## Render verdict ownership (Lane B declares no pixel verdict)

Lane B performs render generation only. The final independent pixel verdict
(BLOCKER / MAJOR counts, Korean glyph legibility, layout defects) belongs to
the W4 independent review (#1507) and is awaited:

```text
LANE_B_PIXEL_VERDICT=NOT_DECLARED
W4_PIXEL_REVIEW=AWAITING_W4_1507
```

## Notes

- This package was regenerated from the exact accepted Lane A source
  (SOURCE_REVISION above) with the generator commit recorded in
  GENERATION_MANIFEST.json. Pre-V3.1 binaries from PR #359 remain historical
  evidence only (see SOURCE_MAPPING.md historical section).
- validator는 시각 검증을 대신하지 않는다. 이 검사는 구조/공식/매핑/리비전
  검증이며, 실제 픽셀 가독성·계층·테이블·브랜드 연속성은 W4 Web CTO pixel
  review (#1507)에서 별도로 확인해야 한다.
- Deterministic: fixed timestamps (2026-09-03), deterministic core properties,
  sorted output lists, real-renderer evidence only.

## Current disposition

```text
CURRENT_V3_1_ARTIFACTS=V3_1_REGENERATED_FROM_ACCEPTED_SOURCE
CURRENT_V3_1_PIXEL_REVIEW=AWAITING_W4_1507
CUSTOMER_SEND_READY=false
DO_NOT_SEND
DRAFT
```
