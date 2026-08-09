# B1 Personal Edition V3 — Issue #454

V3 is an art-direction reset after the owner rejected V2 in live Production. It is not a V2 polish pass.

## Required status

```text
B1_V3_UI_REVIEW_READY
OWNER_UI_APPROVED=false
UX_BLOCKED_BY_OWNER_UI_DECISION
BACKEND_UNCHANGED
PR_OPEN_DRAFT_UNMERGED
```

Technical validation does not constitute owner visual approval.

## V3 thesis

**ASSEMBLY → BIND → READ → RECUT**

The participant experience uses one continuous spatial system to make the product transformation legible:

1. raw private fragments arrive as notes, timestamps, snippets and marginal cues;
2. fragments gather around a binding axis and resolve into a singular Edition object;
3. the Edition opens into a controlled long-form reading surface;
4. reader feedback becomes a visible editorial recut for the next Edition.

This grammar replaces the rejected V2 beige/paper-photo/split-layout direction. Participant core surfaces do not depend on decorative raster photography.

## Core surfaces

- canonical owner-review root `/`
- entry `/preview/intro/`
- Private Library `/preview/participant/published/`
- source capture `/preview/participant/input/`
- Edition Read `/preview/participant/editions/modal-preview-edition/`
- editorial feedback `/preview/participant/editions/modal-preview-edition/feedback/`
- feedback adaptation / recut `/preview/participant/editions/modal-preview-edition/adaptation/`
- archive `/preview/participant/history/`
- operator queue and proofing surfaces under `/admin/`

## Owner-facing chrome boundary

The canonical static root is a product surface. It must not visually expose:

- `UI Preview · Synthetic data · No persistence`
- `Personal Edition UI Preview`
- `프리뷰 목록`

Static QA pages may retain explicit debug scaffolding for technical validation. The root hides the injected QA banner and renders the V3 product composition instead of a preview index.

## Browser gate

`tests/test_ui_v3_browser_454.py` validates the exact V3 review matrix in real system Chrome/Chromium:

- desktop `1440 × 1100`
- tablet `768 × 1024`
- mobile `390 × 844`

Eight surfaces are captured in each viewport: canonical root, Library, Write, Read, Feedback, Adaptation, operator queue, and operator content review — 24 screenshots total.

The gate also checks:

- no horizontal overflow;
- no broken local images;
- no unexpected local HTTP errors;
- no unexpected external requests;
- no page/runtime errors;
- visible keyboard focus;
- `prefers-reduced-motion: reduce`;
- meaningful non-reduced V3 assembly motion;
- root debug chrome hidden.

Existing Personal Edition browser and regression suites remain active to preserve participant/operator routes, URL slug vs issue-number separation, privacy/human-review semantics, and backend contracts.
