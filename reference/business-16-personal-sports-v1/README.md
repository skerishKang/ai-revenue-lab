# Personal Sports — Phase 1 visual UI reference

Status: `reference-only` · `UI_ONLY` · `UI_REVIEW_READY`

This folder contains the Phase 1 visual reference for proposed Business 16, **Personal Sports / 나의 스포츠 채널**.

## Product promise

> 한 팬이 응원하는 팀과 선수의 경기 전 브리핑, 관전 포인트, 경기 후 복기, 선수 흐름과 다음 시청 계획을 이어서 보는 개인 스포츠 채널.

## Synthetic fixture

- Fictional club: `해람 시티`
- Fictional opponent: `북항 유나이티드`
- Fictional player: `윤재호`
- Truth label: `합성 경기 데이터 / Synthetic sports fixture`

No real club, player, league, broadcaster, score, logo, uniform or result is used.

## Review states

1. 오늘의 매치데이
2. 경기 전 브리핑
3. 관전 노트
4. 경기 복기
5. 선수 렌즈
6. 시즌 흐름
7. 모바일 390px 매치 브리핑

State controls and motion replay exist only for Phase 1 visual review. They do not establish accepted UX.

## Explicit non-goals

No live scores, sports API, streaming, login, persistence, notification, odds, gambling, fantasy sports, payment, real AI, UX or backend is implemented.

## Run locally

```bash
python3 -m http.server 4173 --directory reference/business-16-personal-sports-v1
```

Open `http://127.0.0.1:4173/`.
