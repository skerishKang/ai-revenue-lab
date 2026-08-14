# VISUAL_QA — Business 35 Customer Package

```text
CURRENT_PRODUCT_AUTHORITY=V3_1_MERGED_PR_370
PRE_V3_1_PIXEL_REVIEW=HISTORICAL_ONLY
V3_1_REGENERATED_ARTIFACTS=NOT_YET_PRODUCED
CURRENT_PRODUCT_VISUAL_QA=PENDING_REGENERATION
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

## What the existing renders prove

The repository contains historical rendered evidence for the pre-V3.1 customer package:

```text
rendered/proposal-01.png ... proposal-10.png
rendered/onepage-1.png
rendered/questionnaire-1.png ... questionnaire-3.png
xlsx-rendered/*.png
```

Those renders are still useful for **historical geometry/pixel provenance**. They do not prove that the package represents the current product accepted in merged PR #370.

## Historical review record

The earlier package went through an initial visual FAIL followed by layout repairs. Historical blockers included:

```text
Slide 3/4/8 headline/text overlap
Slide 2 spacing
One-page box / next-action overlap
Questionnaire pagination / title wrap / answer-space / internal-marker defects
```

The generation scripts were then repaired and historical structural checks reported zero blocker/major geometry defects. Later package evidence also recorded PDF page counts, XLSX formula checks, render counts, and manifest integrity.

All of that is retained as **pre-V3.1 evidence only**.

## Why it is not a current visual PASS

After those binaries were generated, Business 35 product authority changed. The accepted current product is:

```text
파디엠 AI 미디어 업무전환 스튜디오
reference/business-35-ai-media-education-dx-v3/
merged PR #370
merged commit 05932da3af774220372f0e9f3716b07cd83511f9
```

The current V3.1 product uses a service-led interactive-studio story and a warm-ivory / dark-forest / restrained-cobalt institutional system. Existing customer binaries were not generated from that current product story or visual continuity contract.

Therefore:

```text
OLD_PIXEL_PASS_DOES_NOT_EQUAL_CURRENT_PRODUCT_PASS
OLD_STRUCTURAL_PASS_DOES_NOT_EQUAL_CURRENT_PRODUCT_PASS
PRE_V3_1_RENDERED_ARTIFACTS=STALE_FOR_SEND
```

## Required next visual QA

After V3.1-aligned source rewrite and regeneration:

1. render every proposal / one-page / questionnaire page again;
2. render all XLSX customer sheets again;
3. verify Korean glyphs, clipping, overlap, readable footers, price labels, and legal/status text;
4. compare first-screen/product framing against `CURRENT_PRODUCT_AUTHORITY.md`;
5. verify the package feels like the same product as V3.1 without blindly cloning web pixels;
6. inspect every generated artifact with an image-capable Web CTO review;
7. record the exact regeneration head and artifact hashes before any send decision.

Current target visual continuity:

```text
warm ivory field
+ dark forest typography
+ restrained cobalt information accents
+ calm institutional / educational tone
+ strong Korean hierarchy
+ no neon / robot / circuit cliché
```

## Current verdict

```text
HISTORICAL_GEOMETRY_EVIDENCE=PRESERVED
HISTORICAL_PIXEL_REVIEW=PRESERVED
CURRENT_V3_1_ARTIFACTS=NOT_YET_GENERATED
CURRENT_V3_1_PIXEL_REVIEW=NOT_YET_RUN
CUSTOMER_SEND_READY=false
DO_NOT_SEND
DO_NOT_MERGE
```
