# Draft PR review notes

This branch is intentionally not owner-approved.

## Technically validated

- new V2 spatial/route visual grammar;
- participant route continuity;
- operator desk reset;
- hidden QA compatibility markers;
- responsive/reduced-motion CSS;
- functional suite: 565 passed / 2 skipped;
- static + real-Chromium preview suite: 76 passed;
- 3 viewports × 8 surfaces = 24/24 Chromium render captures;
- no horizontal overflow, broken local images, unexpected external requests, page/runtime errors;
- keyboard focus-visible and reduced-motion checks passed;
- meaningful non-reduced travel hero motion passed;
- startup health smoke and `git diff --check` passed.

## Remaining before final owner visual review

- replace the legacy synthetic Busan image files with destination-quality local assets;
- document asset provenance/license in `docs/IMAGE_SOURCES.md`;
- rerun the same real-Chromium gate after asset replacement and verify responsive crops.

Do not mark `OWNER_UI_APPROVED=true` until the owner reviews the actual live Production surface after an explicitly authorized merge.
