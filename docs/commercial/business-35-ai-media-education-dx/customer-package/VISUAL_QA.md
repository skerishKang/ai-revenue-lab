# VISUAL_QA — Business 35 Customer-Facing Master Package

```
CUSTOMER-FACING MASTER
FINAL IDENTITY REQUIRED
LEGAL REVIEW REQUIRED
NOT YET SENT
```

## Review scope and tool

```text
Rendered pages reviewed: 15 (proposal 10, one-page 1, questionnaire 4)
Model/Viewer used: NONE — this model does not support image input
Review type: STRUCTURAL + TEXT-BASED VALIDATION ONLY
```

**Important:** the executing model (`deepseek-v4-flash`) cannot read image files. Direct pixel-level visual review of the rendered PNGs was **not performed**. The `VISUAL_QA_PASS` / "한글 깨짐 없음" / "객체 겹침 없음" declarations are therefore **not claimed**.

Structural and text-based verification was performed instead:

```text
- PDF text extraction (pdftotext): broken-glyph markers, clipped text markers, page count
- PPTX geometry check (python-pptx): shape bounds within slide bounds
- Rendered PNG existence and count (15)
- Footer/status structure on each slide
- Forbidden phrases, unsourced numbers, customer/performance claims
- Spreadsheet formula and range-warning logic (openpyxl simulation)
```

## Reviewed files (15)

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
rendered/questionnaire-4.png
```

These pages derive from the package outputs `Business35_Master_Proposal_10p`, `Business35_OnePage_Offer`, and `Business35_Diagnostic_Questionnaire` (PDF/PPTX/DOCX regenerated from the build scripts).

## Per-page status

```text
proposal-01..10 — PRESENT (10 files), text-based checks passed, no glyph/clip markers
onepage-1       — PRESENT (1 file), text-based checks passed
questionnaire-1..4 — PRESENT (4 files), text-based checks passed
```

## Issues found (structural/text-based)

```text
1. [MAJOR → FIXED] Status footer repeated the full 4-line status on every slide at 9pt
   → restructured: cover = full status, inner = "DRAFT MASTER · LEGAL REVIEW REQUIRED",
     last = "제공자 정보 최종 확정 필요"; font raised to 11pt
2. [MINOR → FIXED] One-page footer status at 9pt → raised to 10pt, provider note separated
3. [MINOR → FIXED] Questionnaire status text at 9pt → raised to 10pt
```

## Remaining minor issues

```text
- Pixel-level visual review pending (requires an image-capable model or browser viewer)
- Rendered PNG visual inspection (overlap, clipping at pixel level) not performed
```

## Repair actions

```text
- validation/build_proposal_pptx.py — footer_mode (cover/inner/last), status font 11pt
- validation/build_one_page_pptx.py — status structure, font 10pt
- validation/build_questionnaire_docx.py — status font 10pt
- All outputs regenerated: PPTX, PDF, DOCX, XLSX, rendered/*.png
- validation/validate_customer_package.py — strengthened (VISUAL_QA checks, slide/footer checks)
```

## New exact head

```text
<EXACT_HEAD_PLACEHOLDER>
```

## Status counts

```text
BLOCKER: 0
MAJOR: 0
MINOR: 2 (recorded above, structural only)
```

## Validator scope note

```text
The validator checks repository structure, file presence, page counts, source linkage,
forbidden claims, and geometry. It does NOT replace visual QA; pixel-level rendering
review still requires an image-capable model or viewer.
```

The automated validator is not a substitute for visual QA. A BLOCKER/MAJOR visual defect can
exist even when the validator passes. 즉, validator 결과가 시각 QA를 대신하지 않는다.
