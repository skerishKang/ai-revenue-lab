# Business 6 · World Feed — Phase 1 Visual UI Reference

## Status

- Phase: **UI_ONLY / Phase 1 visual UI**
- Current review verdict entering this correction: **UI_NOT_READY**
- Visual direction: **Personal World Dispatch / 나의 세계 편집면**
- Issue: `#155`
- Draft PR: `#158`
- Focused-correction starting head: `99981006dcf792c359795a0c618c92a800d65c0d`
- Hosted review: `https://ai-revenue-world-feed.pages.dev`

This directory remains a static visual reference. It does not implement accepted UX, recommendation logic, current-information ingestion, authentication, persistence, APIs, AI providers, analytics, notifications, billing, or deployment logic.

> 시각 검토용 합성 콘텐츠이며 현재 사실을 나타내지 않습니다.

## Focused correction v2

The correction keeps the existing seven-state product direction and concentrates on:

- Korean display-title scale and controlled wrapping;
- stronger legibility for navigation, body, source, and time text;
- reduced vertical whitespace and tighter editorial rhythm;
- rebalanced Home hero, signal rail, and discovery mosaic;
- reduced Topic heading scale and aligned A/B/C stack;
- active-looking After composition using order, size, and emphasis instead of opacity;
- reduced repetition of harbor and pottery imagery;
- two additional repository-local images: `neighborhood-bookshop.svg` and `maker-studio.svg`;
- quieter Phase 1 and development-language treatment;
- actual 390px responsive evidence;
- preserved Horizon Shift and reduced-motion behavior.

## Stylesheet structure

The former monolithic `styles.css` is removed. Styles are split by responsibility:

```text
styles/
├─ tokens.css
├─ base.css
├─ layout.css
├─ components.css
└─ states/
   ├─ home-topic.css
   ├─ story-why.css
   └─ adjusted-mobile-motion.css
```

All CSS and JavaScript resources use the deterministic query:

```text
world-feed-20260726-2
```

## Review states

1. `home`
2. `topic`
3. `story`
4. `why`
5. `adjusted`
6. `mobile`
7. `motion`

The controls are for visual inspection only. They do not establish final navigation or preference UX.
