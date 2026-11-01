# StoryMemory v3.3.5 — Static Expansion Readiness

Date: 2026-08-26 (Asia/Seoul)
Business: B61 StoryMemory
Base: v3.3.4
Deployment: DEFERRED_TO_BI_PORTAL
Portal target: /b61/

## Scope

Prepare the existing Static Content Repository Adapter to consume future SM-038/SM-039 runtime corpus assets without another reader architecture rewrite.

No new Bible/Gutenberg source body is claimed in this package. The v3.3.5 `dist/content/**` tree is byte-identical to v3.3.4.

## Changes

- Expanded static work mapping:
  - `book:iliad -> iliad`
  - `book:odyssey -> odyssey`
  - `book:crime-and-punishment -> crime-and-punishment`
  - `bible:1cor -> bible-web`
  - `book:pride-and-prejudice -> pride-and-prejudice`
  - `book:alice-in-wonderland -> alice-in-wonderland`
- Added `StaticAdapter.loadUnitByKey()` while preserving ordinal loading.
- Added Bible static SourceRef normalization using `{book, chapter, verse}` canonical locator metadata.
- Bible chapter loading now tries static `book:<USFM>:chapter:<NNN>` first and falls back to existing remote/prototype behavior when the static work/unit is absent.
- Static passage normalization now preserves row-level `locator`, `chapter_label`, `verse_label`, and translation policy.
- Canonical Alice work key aligned to `alice-in-wonderland` across the acquisition/runtime handoff.

## QA

- Inline JavaScript syntax: 6/6 PASS.
- Synthetic static expansion contract: PASS.
  - all six public-content frontend mappings verified.
  - `bible:1cor` resolves to `bible-web`.
  - `book:1CO:chapter:001` loads as static.
  - locator `bible:web:1CO:1:1`, book/chapter/verse and KO text preserved.
  - prose static unit load PASS.
- Existing content tree regression: 192/192 files, missing 0, extra 0, changed 0.

## Boundaries

- No official ENGWEBP/Gutenberg raw-byte freeze claimed.
- No Neon main mutation.
- No full-book-body Neon import.
- No Cloudflare deployment.
- No new Pages project.
- No DNS/custom domain change.
- No `apps/padiem-lab/**` or `apps/portfolio-console/**` mutation.
- Existing StoryMemory workspace/source path unchanged.
