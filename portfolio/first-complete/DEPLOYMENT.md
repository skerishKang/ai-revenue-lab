# AI Revenue Lab B01–B15 First Complete Portfolio — Deployment Record

Date: 2026-08-16
Branch: `portfolio/first-complete-20260816`
Cloudflare Pages project: `ai-revenue-final-portfolio`
Production URL: `https://ai-revenue-final-portfolio.pages.dev`
Final evidence deployment preview URL: `https://c3f3f947.ai-revenue-final-portfolio.pages.dev`

## Scope

This is the first unified showcase for B01–B15. It is separate from the operations-oriented Portfolio Console.

- 15 scopes represented.
- 12 internal portfolio-ready products represented as PASS/FREEZE or owner-adopted.
- B05 is explicitly represented as an external successor lineage to DanjiOn.
- B09 is explicitly represented as BLOCKED for clean-master asset-byte integration only; it is not presented as final.
- B14 V4 is represented as OWNER ADOPTED and points to the adopted 22-surface master rather than pretending an older Pages deployment is current authority.
- B15 is represented as DESIGN COMPLETE / CANDIDATE and is not silently promoted into the canonical Business Registry.

## Product-evidence previews

The deployed bundle includes browser-captured screenshots of the public product surfaces for B01, B02, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, and B15. B03 and B14 intentionally use authority/evidence panels instead of stale public surfaces.

## QA

GitHub Actions run: `31944085925`
Artifact: `portfolio-first-complete-review-20260816`
Artifact ID: `9262813610`
Artifact SHA-256: `64368c5698884fb79c5917d952552e60900699b378e9835866eef880a8b7dfd6`

QA result:

```text
SOURCE_CONTRACT=PASS
PREVIEW_CAPTURE=b01,b02,b04,b05,b06,b07,b08,b09,b10,b11,b12,b13,b15 = PASS
STATIC_PREVIEW_PATCH=PASS
PRODUCTION_CONTENT_QA=PASS
SCREENSHOT_QA=PASS
DESKTOP=1440x1100 full-page
MOBILE=390x844 full-page
```

The final desktop and mobile captures were independently inspected after the run. Product-evidence imagery is visible in the portfolio preview frames, the B09 blocked state remains visible, and B03/B14 retain evidence-panel treatment.

## Rollback evidence

The production deployment that existed before the first portfolio replacement in this work session was:

- Deployment ID: `883fc2dc-a67e-4cef-a731-26457a88bb75`
- Created: `2026-08-15T07:53:42.764863Z`

Cloudflare retains prior deployment history for rollback.

## Safety closure

The temporary deployment workflow was deleted from the branch after successful production and screenshot verification. Individual B01–B15 Pages projects were not modified by this portfolio build.
