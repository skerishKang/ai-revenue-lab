# Business 6 · World Feed — Phase 2 UX Slice 1

## Status

- Phase: **UX_ONLY / Phase 2 frontend prototype**
- Issue: `#165`
- Starting base: `48807067a261d8f1ca3814b4b26758dd6947788a`
- Accepted visual baseline: PR `#158`, visual head `cde6677e71172125cb3a0406f6ba6a79e0467d36`
- Branch: `feat/business-06-world-feed-ux-165`
- Visual direction: **Personal World Dispatch / 나의 세계 편집면**
- Backend: **FROZEN**

This slice converts the approved visual reference into one deterministic frontend journey using synthetic local content and in-memory state only.

## Primary journey

```text
나의 피드
→ 가까운 동네 또는 장소와 문화 선택
→ 이야기 열기
→ 출처와 등장 이유 확인
→ 동네 소식 더 보기 적용
→ 변경된 피드 확인
→ 실행 취소 또는 전체 초기화
→ 이전 피드 위치와 포커스로 복귀
```

## Direct routes

```text
#feed
#nearby
#culture
#story
#why
#preferences
```

Browser Back and Forward operate through deterministic History API entries. Opening a story captures the originating route, scroll position, and focusable control. Returning restores that context.

## Frontend-only state

- selected route and stream;
- one preference: `동네 소식 더 보기`;
- immediate feed-order change;
- Undo and full Reset;
- source-action dialog that explicitly performs no external request.

No `localStorage`, cookie, account, API, database, crawler, live provider, or network data is used.

## Source structure

```text
index.html
scripts/
├─ feed-state.js
├─ navigation.js
├─ story-state.js
├─ preference-state.js
└─ ux-app.js
styles/
├─ tokens.css
├─ base.css
├─ layout.css
├─ components.css
├─ states/
│  ├─ home-topic.css
│  ├─ story-why.css
│  └─ adjusted-mobile-motion.css
└─ journeys/
   └─ primary-journey.css
```

All loaded CSS and JavaScript use:

```text
world-feed-20260726-3
```

Every authored or materially modified source file remains at or below 500 physical lines.

## Explicitly deferred

- loading skeleton;
- empty filter result;
- recoverable error and retry;
- unavailable story or source state;
- onboarding and account history;
- authentication and persistence;
- backend, API, DB, crawling, AI, notifications, billing, and deployment configuration.

These belong to later UX slices or separately authorized phases.
