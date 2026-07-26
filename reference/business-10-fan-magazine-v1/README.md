# Business 10 · Fan Magazine — Phase 1 Visual UI Reference

## Status

- Product: **나만의 팬 매거진 / Fan Magazine**
- Phase: **UI_ONLY / Phase 1 visual reference**
- Issue: `#171`
- Parent queue: `#154`
- Starting base: `48807067a261d8f1ca3814b4b26758dd6947788a`
- Branch: `feat/business-10-fan-magazine-ui`
- Visual direction: **Personal Cover Story / 나만의 커버스토리**
- Current verdict: **UI_NOT_READY** pending Web CTO and user review
- Status flags: `reference-only`, `UI_ONLY`, `UI_NOT_READY`

This workspace is a static visual reference. It does not implement accepted UX, real celebrity data, search, crawling, current news, personalization logic, accounts, persistence, APIs, AI providers, commerce, subscriptions, sharing, analytics, or deployment.

## Fictional subject

The entire issue uses one deterministic fictional subject:

- Name: **서하린**
- Role: fictional singer-songwriter and stage director
- Fictional body of work: `잔광`, `미세한 파도`, `은빛 계단`, `여름의 뒷면`
- Rights boundary: no real face, name, photograph, logo, album jacket, performance still, team mark, or private fan record is used.

## Review states

1. `cover` — 이번 호 표지
2. `feature` — 커버스토리
3. `trajectory` — 작품의 궤적
4. `rediscovery` — 다시 보는 순간
5. `fan-note` — 나의 팬 노트
6. `mobile` — 390px 독립 모바일 구성
7. `reveal` — Cover Reveal motion

The state controls exist only for visual inspection. They do not define final product navigation or an accepted user journey.

## Files and responsibilities

```text
styles/tokens.css                 visual tokens
styles/base.css                   reset, typography, accessibility
styles/layout.css                 review shell and editorial grids
styles/components.css             repeated magazine components
styles/states/cover-feature.css   cover and feature spread
styles/states/archive-note.css    chronology, rediscovery, fan note
styles/states/mobile-reveal.css   mobile edition and signature motion
scripts/review-state.js           deterministic state switching and motion preview
assets/images/*.svg               repository-local synthetic visual assets
evidence/*                        text-only validation evidence
```

## Run

```bash
cd reference/business-10-fan-magazine-v1
python3 -m http.server 4173
```

Open `http://127.0.0.1:4173/#cover`.

## Asset version

Every loaded CSS and JavaScript path uses:

```text
fan-magazine-20260726-1
```

Local SVG image references use the same deterministic token.

## Review boundaries

- no framework or build system;
- no external font or library;
- no external image hotlink;
- no runtime external request;
- no `localStorage`, cookies, API, service worker, or database;
- no search, follow, save, comment, upload, purchase, ticket, merchandise, subscription, or share control;
- no `UI_APPROVED` claim;
- no UX or backend authorization;
- no production or hosted-review deployment configuration.
