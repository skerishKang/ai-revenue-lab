# B62 Padiem Chat — Phase 1 Rendered QA

Date: 2026-08-25 KST
Parent: #713
Execution: #715
Draft PR: #714

## Verdict

```text
ANCHOR_IMPLEMENTED = YES
ANCHOR_REVIEW_READY = YES
ANCHOR_DIRECTION_LOCKED = NO
```

This is a review-ready visual/UX anchor, not an owner-approved design lock and not a live AI deployment.

## Render method

A local mirror of the Phase 1 static workspace was rendered with headless Chromium through Playwright using only the repository HTML/CSS/JavaScript.

No web font, image CDN, model endpoint, search endpoint, API, account, database or other network resource was used.

Reviewed viewport sizes:

```text
Desktop home: 1440 × 1100
Mobile home:   390 × 844
Desktop chat:  1440 × 900
Mobile chat:   390 × 844
Desktop search: 1440 × 900
Mobile search:  390 × 844
```

## Finding 1 — hidden-state rendering bug

Initial rendered home review exposed a real defect:

```text
attachmentChip[hidden]
```

was still visible because the authored `.attachment-chip { display: grid; }` rule could override the browser's hidden presentation.

Fix:

```css
[hidden] { display: none !important; }
```

The first screen was re-rendered after the fix.

Regression coverage was added to `tests/static-contract.test.cjs`.

## Desktop home review

PASS observations:

- Padiem Chat identity visible without a provider/logo wall;
- `자동 추천` remains secondary to the conversation entry;
- `무엇을 도와드릴까요?` is the clear first-screen question;
- composer is visually dominant and immediately understandable;
- `파일` and `웹 검색` are visible but secondary;
- Projects is visibly unavailable/`준비 중` rather than falsely live;
- no synthetic attachment appears before activation;
- no dashboard/card-wall feeling;
- large unused space preserves calm rather than crowding the user.

## Mobile 390 review

PASS observations:

- horizontal overflow: `0px`;
- hamburger / model / login row stays within 390px;
- headline remains readable without browser zoom;
- four starter actions become one-column touch-friendly cards;
- composer remains visible and usable at the bottom;
- file/search controls remain text-labelled;
- no sidebar content is compressed into the mobile canvas before opening the drawer.

## Chat state review

Automated rendered state facts:

```text
Desktop chat horizontal overflow = 0
Mobile chat horizontal overflow  = 0
Rendered messages                = 2
Demo labels                      = 1
Source cards                     = 0
state                             = chat
```

Visual observations:

- user bubble is distinct without excessive styling;
- assistant content reads like normal prose rather than a technical log;
- `데모 응답` is visible next to Padiem Chat identity;
- mobile answer remains readable at normal zoom;
- composer remains available for the next turn.

## Search state review

Automated rendered state facts:

```text
Desktop search horizontal overflow = 0
Mobile search horizontal overflow  = 0
Rendered messages                  = 2
Demo labels                        = 1
Source cards                       = 2
state                               = search
```

Visual observations:

- answer clearly says `웹 검색 데모 상태`;
- source cards are readable on 390px;
- both source cards explicitly say `실제 검색 결과 아님`;
- active `웹 검색` tool state remains visible in the composer.

## Static validation after rendered fix

```text
node --check app.js = PASS
node --test tests/static-contract.test.cjs = PASS 7/7
```

Contracts now cover:

1. simple first-screen identity;
2. deterministic review states;
3. demo/live truth boundary;
4. zero live fetch / external runtime assets;
5. accessibility basics;
6. hidden-state visual contract;
7. Projects future-only contract.

## Remaining owner gate

Do not convert this Draft PR into an accepted visual direction solely from this technical/render QA.

Owner review should answer:

```text
Does this feel simple enough that a non-technical family member would immediately type a question?
Does it feel like a credible Padiem general AI rather than an internal developer console?
Is the restrained light/violet direction acceptable as the baseline for runtime work?
```

If yes:

```text
ANCHOR_DIRECTION_LOCKED
→ open separate B62 live-runtime contract issue
```

If no, revise only the anchor visual hierarchy before adding backend/runtime complexity.
