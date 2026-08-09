# Creator Mini-Media — Phase 1 visual UI reference

Status: `reference-only` · `UI_ONLY` · `UI_NOT_READY`

This folder contains the Phase 1 visual reference for proposed Business 12, **Creator Mini-Media / 크리에이터 미니미디어**.

## Product promise

> 1인 창작자에게 기사·뉴스레터·게시물·영상 대본을 함께 만드는 작은 병렬 편집국을 제공한다.

## Synthetic editorial fixture

- Creator: `윤서진 · 도시생활 에디터`
- Desk edition: `저녁의 골목 · 제07호`
- Source idea: `동네의 오래된 시장이 저녁 문화 공간으로 바뀌는 과정`
- Core line: `낮의 장사가 끝난 자리에서, 동네의 두 번째 시간이 시작된다.`

## Review states

1. 오늘의 편집 데스크
2. 대표 기사
3. 뉴스레터 한 호
4. 짧은 채널 묶음
5. 영상 대본 보드
6. 모바일 390px
7. Format Relay / 포맷 릴레이

The state controls exist only to inspect visual composition and motion. They are not accepted navigation or UX.

## Explicit non-goals

No authentication, input, editing, AI generation, persistence, publishing, scheduling, analytics, collaboration, API, database, payments, notifications, or deployment is implemented.

## Run locally

```bash
python3 -m http.server 4173 --directory reference/business-12-creator-mini-media-v1
```

Open `http://127.0.0.1:4173/`.
