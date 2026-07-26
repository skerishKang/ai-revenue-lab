# Business 6 · World Feed — Phase 1 Visual UI Reference

## Status

- Phase: **Phase 1 — visual UI only**
- Visual direction: **Personal World Dispatch / 나의 세계 편집면**
- Issue: `#155`
- Parent queue: `#154`
- Product decision: `#98`
- Existing synthetic research baseline: `#36`
- Contract-time `main`: `67f1d1721ef779ffcb74d076e6f5436ebb05c4f3`
- Fetched implementation base: `3fb95ea5f424f91b95851a778bffeb531cbc015d`

This directory is a static visual reference. It does not implement accepted UX, recommendation logic, current information ingestion, authentication, persistence, APIs, AI providers, analytics, notifications, billing, or deployment.

> 시각 검토용 합성 콘텐츠이며 현재 사실을 나타내지 않습니다.

## Product promise

세계와 지역에서 나오는 문화·연예·장소·여행지·동네·생활 이야기와 제한적인 스포츠를 한 사람의 관심에 맞춰 짧고 가볍게 보여주는 개인화 피드.

## Visual thesis

World Feed is presented as a personal editorial dispatch rather than a newspaper portal, social-network clone, or AI dashboard.

- warm paper canvas and ink-first typography;
- vermilion editorial accent;
- muted moss/teal signal for nearby context;
- one dominant image with asymmetric supporting imagery;
- mixed post anatomy rather than uniform rounded cards;
- visible but secondary source and time lines;
- Korean-first short copy;
- no purple/blue AI gradient, glassmorphism, robot/brain/sparkle motif, fake metrics, or decorative charts.

## Required review states

1. `home` — mixed world / nearby / personal feed identity.
2. `topic` — `장소와 동네` stream with an alternate `공예와 손` visual switch.
3. `story` — compact detail with source-forward context and related discoveries.
4. `why` — plain-language personalization explanation without scores or ranking formulas.
5. `adjusted` — before/after visual weight change.
6. `mobile` — 390px composition preview and actual responsive behavior.
7. `motion` — Horizon Shift transition preview.

## Local review

From this directory:

```bash
python3 -m http.server 4173
```

Then open:

```text
http://127.0.0.1:4173/
```

Direct state hashes are supported:

```text
#home
#topic
#story
#why
#adjusted
#mobile
#motion
```

Review controls are native buttons. The state bar supports click, `Tab`, `Enter`, `Space`, `ArrowLeft`, `ArrowRight`, `Home`, and `End`. Focus states are visible.

## Scope boundaries

Implemented:

- static HTML/CSS/JavaScript;
- synthetic Korean content;
- repository-local SVG imagery;
- visual state switching;
- topic visual switch;
- detail layer presentation;
- before/after comparison;
- Horizon Shift motion;
- reduced-motion fallback;
- desktop/mobile evidence and browser checks.

Not implemented:

- signup, login, onboarding, final navigation, durable user input, actual recommendation, personalization storage, API, database, crawler, current news, AI model call, payment, notification, analytics, or deployment.

## Files

- `REFERENCE_NOTES.md` — comparative product and editorial research.
- `IMAGE_SOURCES.md` — local asset provenance and rights status.
- `MOTION_SPEC.md` — Horizon Shift timing and reduced-motion contract.
- `index.html` — seven visual review states.
- `styles.css` — editorial visual system and responsive composition.
- `app.js` — visual state switching and deterministic motion preview only.
- `assets/images/**` — self-created local SVG illustrations.
- `evidence/**` — captured states, motion proof, and validation logs.
