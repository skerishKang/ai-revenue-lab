# Business 7 · Personal Meaning Map — Phase 1 Visual UI Reference

## Status

- Phase: **UI_ONLY / Phase 1 visual UI**
- Current verdict: **UI_NOT_READY** pending Web CTO and user visual review
- Product status: candidate / proposed number `7`
- Visual direction: **Intimate Cartography / 사적인 지도책**
- Issue: `#166`
- Parent queue: `#154`
- Exact starting base: `48807067a261d8f1ca3814b4b26758dd6947788a`

This directory is a static, synthetic visual reference. It does not implement accepted UX, personal-data import, accounts, persistence, geographic routing, live AI, APIs, databases, analytics, or deployment.

> 모든 이름·장소·날짜·기록은 식별 불가능한 합성 자료이며 시각 검토용입니다.

## Product promise

> 장소·사람·사건·물건이 한 사람에게 갖는 의미와 서로의 관계를, 시간이 지나며 변하는 사적인 지도로 보여준다.

## Visual states

1. `overview` — 오늘의 의미 지도
2. `person` — 사람의 궤적
3. `place` — 장소의 층
4. `event-object` — 사건과 물건
5. `explanation` — 왜 이어졌나요
6. `mobile` — 모바일 390px 구성
7. `ripple` — Meaning Ripple / 의미 파동

## Review controls

- 상단의 7개 인덱스 버튼으로 상태 전환
- `←` / `→` 또는 `Home` / `End`로 키보드 상태 이동
- 지도 안의 대표 항목 선택
- 설명 패널 열기
- 의미 파동 다시 보기

These controls exist only to inspect the visual system and motion. They do not establish final navigation or interaction design.

## Asset version

Every loaded CSS and JavaScript resource uses:

```text
personal-meaning-map-20260726-1
```

## Run

```bash
cd reference/business-07-personal-meaning-map-v1
python -m http.server 4177
# open http://127.0.0.1:4177/
```
