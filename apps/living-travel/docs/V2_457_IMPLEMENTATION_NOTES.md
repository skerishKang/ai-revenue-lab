# B2 Living Travel V2 — Issue #457 implementation notes

Status: in-progress Draft review build.

## Implemented visual system

The V2 shell replaces the centered preview/card demo language with one continuous travel grammar:

`DESTINATION → PREFERENCE SHAPING → ROUTE ASSEMBLY → HUMAN REVIEW → EDITION → RECUT → ARCHIVE`

Primary visual materials:

- destination-scale typography;
- route stops and time cues;
- daily travel density;
- full-bleed place moments;
- spatial before/after recut;
- travel archive/ticket language;
- editorial-control operator desk.

Owner-facing QA strings required by historical static tests remain in the DOM as visually-hidden compatibility markers. They are not intended to appear in the V2 visual shell.

## Redesigned surfaces

- canonical root `/`;
- `demo/intro.html`;
- `demo/preferences.html`;
- `demo/generation.html`;
- `demo/pending.html`;
- `demo/traveler-home.html`;
- `demo/edition.html`;
- `demo/feedback.html`;
- `demo/comparison.html`;
- `demo/edition-2.html`;
- `demo/history.html`;
- `operator/login.html`;
- `operator/queue.html`;
- `operator/review.html`.

## Compatibility / scope

- no backend/Auth/DB/domain/provider changes;
- no external runtime fonts, scripts, trackers, or image URLs;
- existing clickable demo route contract retained;
- required CTA text retained for static contract tests;
- reduced-motion CSS included;
- responsive breakpoints included.

## Remaining visual gate before owner approval

The HTML currently reuses the repository's existing local Busan demo image files while the layout/system is rebuilt. Those image files came from the older synthetic/procedural preview set and do **not** satisfy Issue #457's final destination-image quality bar.

Before `B2_V2_UI_REVIEW_READY` can be asserted as a final art-direction review build, replace the legacy synthetic image set with locally stored high-quality licensed/CC0 or intentionally generated travel assets and document provenance in `docs/IMAGE_SOURCES.md`.

Do not mark `OWNER_UI_APPROVED=true` until the owner reviews the actual live surface.
