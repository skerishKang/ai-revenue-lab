# Business 57 · Classic Literature Translation Studio

## Status

```text
UI_ONLY
CONTRACT_DEMO
PUBLIC_DOMAIN_AND_SYNTHETIC_FIXTURES_ONLY
UI_REVIEW_READY
NOT_UI_APPROVED
NOT_DEPLOYED_PENDING_UI_APPROVAL
```

This workspace is the Phase 1 visual reference for **고전문학 번역실 / Classic Literature Translation Studio**.

Its primary edition is **Original-Fidelity Translation / 원전 보존 번역**. A separate modern-reading edition must disclose every material simplification, interpretation and loss.

## Seven review states

1. `library` — Translation library / 번역 서가
2. `source-fidelity` — Source and original-fidelity spread / 원문·원전 보존본
3. `comparison` — Original-fidelity versus modern-reading comparison / 두 번역판 비교
4. `ledger` — Translation decision ledger / 번역 판단 기록
5. `poetry` — Classical poetry edition / 고전시 번역판
6. `mobile` — 390px-first mobile reading edition / 모바일 읽기
7. `weave` — Translation Weave / 번역 결 엮기

## Source and contract boundary

The public repository contains only:

- a short *Frankenstein* passage verified against Project Gutenberg eBook #41445, the 1818 edition;
- a short *The Sick Rose* stanza with its textual source recorded;
- Korean translations newly authored for this UI reference;
- one repository-local original SVG.

It contains no protected modern Korean translation, living-author manuscript, licensed private corpus, model adapter, customer material, publishing approval or endorsement claim.

See:

- `RIGHTS_AND_SOURCES.md`
- `IMAGE_SOURCES.md`
- `REFERENCE_NOTES.md`

## Interaction and accessibility

- seven named tab controls with tab/tabpanel semantics;
- Left/Right Arrow movement while a state tab has focus;
- visible keyboard focus;
- source-language attributes on English passages;
- text labels accompany every colour-coded review state;
- mobile source reveal retains an accessible expanded state;
- deterministic `Translation Weave` replay;
- reduced-motion information equivalence.

## Signature motion

`Translation Weave` has a computed maximum end of `680ms`.

```text
Completion: final animationend event
Fixed timer: none
Geometry shift: none
Focus movement: none
Scroll movement: none
Replay 1 / replay 2 final state: equivalent
Reduced-motion final information: equivalent
```

See `MOTION_SPEC.md` and `evidence/browser-validation.json`.

## Technical boundary

- semantic HTML, responsive CSS and minimal JavaScript;
- no gradients, external fonts, external runtime assets, framework, API or model call;
- no upload, storage, persistence, authentication, billing or publishing;
- deterministic asset version: `classic-literature-translation-20260728-2`.

## Validation

From this directory:

```bash
python evidence/validate_static.py
python evidence/validate_browser.py
```

Repository-level whitespace check:

```bash
git diff --check
```

The browser validator uses installed Chromium, renders the actual HTML/CSS/JS bytes through an inline local harness because localhost navigation is blocked in the validation container, and records the harness mode in machine-readable evidence.

## Phase gate

Keep PR #220 OPEN, Draft and unmerged. This implementation does not declare `UI_APPROVED`, start UX, authorize backend work or deploy. Static deployment requires a separate exact-head approval and deployment operation.
