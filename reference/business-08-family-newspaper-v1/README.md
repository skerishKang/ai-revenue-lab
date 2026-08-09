# Business 8 · 우리 가족 신문 / Family Newspaper

Phase 1 visual UI reference for Issue #168 under permanent portfolio queue #154.

## Product promise

> 가족의 사진·일정·대화·기념일·작은 사건을 한 호의 가족 신문으로 편집해, 함께 보고 오래 남길 수 있게 한다.

## Boundary

- Status: `UI_ONLY`
- Current verdict: `UI_NOT_READY` pending Web CTO and user visual review
- Content: deterministic synthetic Korean family records only
- Assets: repository-local original SVG illustrations only
- Interaction: seven-state visual review, source-note disclosure, keyboard state movement, and Page Fold replay
- Not implemented: final UX, accounts, invitations, upload, editing, chat, calendar sync, persistence, AI, APIs, databases, printing, deployment

## Run locally

From the repository root:

```bash
python -m http.server 4173 --directory reference/business-08-family-newspaper-v1
```

Open `http://127.0.0.1:4173/index.html`.

Direct review states are available through the deterministic `state` query:

```text
?state=front
?state=news
?state=photos
?state=calendar
?state=sources
?state=mobile
?state=fold
```

## Review controls

- Click the seven state buttons.
- Use the previous/next arrow controls.
- While a state button is focused, use Left/Right/Home/End.
- Outside controls, `[` and `]` move between states.
- On Page Fold, press `R` or use the replay button.
- The source note uses a single disclosure button.

## Structure

- `index.html`: review shell and deterministic asset loaders
- `styles/tokens.css`: visual tokens
- `styles/base.css`: global paper, type, focus, and boundary rules
- `styles/layout.css`: review shell, masthead, publication layout, responsive foundation
- `styles/components.css`: shared editorial components
- `styles/states/front-page.css`: first-page composition
- `styles/states/sections.css`: news, photo, almanac, source, and Page Fold compositions
- `styles/states/mobile.css`: independent 390px edition
- `scripts/states/*-markup.js`: readable state-specific synthetic editorial markup
- `scripts/render-states.js`: deterministic state markup assembly
- `scripts/review-state.js`: minimal review-only state and motion controls
- `assets/images/**`: repository-local synthetic SVG assets
- `evidence/**`: text validation records only

## Asset version

All loaded CSS and JavaScript use:

```text
family-newspaper-20260726-1
```

No external runtime request, remote font, hotlinked image, API, localStorage, or cookie is used.
