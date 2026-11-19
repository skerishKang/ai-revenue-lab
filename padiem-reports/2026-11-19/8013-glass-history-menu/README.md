# #8013 — glass 대화 ⋮ 메뉴: 불투명 판·행 아래/위

기준: main `d5d0a07` (#8034 병합 뒤), 2026-11-19.
대상: `.history-actions-menu` (glass).

## 이기는 규칙 — 전/후

이슈 본문에는 공용 규칙을 `0,5,2`로 적었지만, 선택자별 CSS 명세 계산은
아래와 같다. 수정 후 glass 전용 규칙은 `0,6,2`로 어느 표기에서도 공용
규칙을 이긴다. 새 `!important`는 없다.

| 역할 | 전 이기는 규칙(파일:줄) | 실제 특이성 | 선언 | 후 glass 규칙(파일:줄) | 실제 특이성 |
|---|---|---|---|---|---|
| 메뉴 배경 | `sidebar-section-polish.css:28-31` | 0,4,2 | `background: var(--sidebar)` | `shared-six-panel-frame.css:290-301` | 0,6,2 |
| 메뉴 배경(동률·뒤 로드) | `sidebar-history-scroll.css:100-103` | 0,3,2 | `background: var(--sidebar)` | 〃 | 〃 |
| 메뉴 위치 | `sidebar-unified.css:152-155` | 0,3,2 | `right:0; top:calc(100% + 4px)` | 〃 | 〃 |
| 덮이던 glass 규칙 | `shared-six-panel-frame.css:290-299` | 0,3,2 | `right:47px; top:2px; background:rgba(248,250,252,.98)` | 〃 | 〃 |

`sidebar-section-polish`의 0,4,2가 가장 높은 공용 배경 규칙이었고,
`sidebar-history-scroll`·`sidebar-unified`는 같은 0,3,2지만 뒤에 로드돼
shared의 glass 규칙을 덮었다. 공용 규칙은 다른 4테마를 위해 건드리지 않고,
glass 선택자에 `.app-shell`·`.history-row`·`.history-actions`를 더해
특이성을 올렸다.

## 계산 값 — glass와 나머지 4테마

| 테마 | 1440 전 bg | 1440 후 bg | 390 전 bg | 390 후 bg | 메뉴 위치 |
|---|---|---|---|---|---|
| padiem-glass | rgba(42,50,59,.46) | **rgba(248,250,252,.98)** | rgba(42,50,59,.46) | **rgba(248,250,252,.98)** | 아래(기본), 공간 없으면 위 |
| light | rgb(241,241,245) | 동일 | 동일 | 동일 | 아래 |
| dark | rgb(14,20,27) | 동일 | 동일 | 동일 | 아래 |
| cinematic | rgba(6,9,15,.88) | 동일 | 동일 | 동일 | 아래 |
| padiem-home | rgba(255,255,255,.62) | 동일 | 동일 | 동일 | 아래 |

- 1440 실측: glass 메뉴 `top=532`, 행 `bottom=529` → 행 바로 아래.
- 390 실측: glass 메뉴 `top=617`, 행 `bottom=614` → 행 바로 아래.
- 390×360 마지막 행 실측: `above`, 메뉴 `top=123`, 메뉴 `bottom=267`,
  행 `top=270` → 행 위. `data-menu-placement="above"`가 붙은 glass에만 적용.
- `z-index`: 메뉴 12, glass 열린 행 30 유지. 나머지 테마 행은 `auto`.
- 호버: glass 항목 `rgba(127,127,127,.16)` = `--control-wash-hover`.

## 변경

- CSS: glass 메뉴 선택자를 0,6,2로 올리고 `right:0; top:calc(100% + 4px);
  background:rgba(248,250,252,.98)`를 되살렸다. 위로 뒤집는 규칙은
  `[data-menu-placement="above"]` + `bottom:calc(100% + 4px)`.
- JS `chat-history-module.js`: glass에서 열릴 때 실제 메뉴 `getBoundingClientRect()`가
  화면 아래(`visualViewport.height - 8`)를 넘을 때만 `above`를 단다.
  resize·목록 scroll에도 다시 계산한다. 다른 테마에는 속성을 달지 않는다.
- #8009의 열린 행 `z-index:30`과 `--control-wash-hover`는 그대로다.

## 검증·캡처

- `tests/test_8013_glass_history_menu.py`: 정적 계약 3 + 브라우저 계약 3
  (1440·390 불투명 판, 아래 열림, 항목 클릭·호버, 390×360 위 뒤집기,
  나머지 4테마 계산값). 전체 관련 시험 **50 passed**.
- 캡처: `before/` 10장(5테마 × 1440/390), `after/` 10장 + `after/glass-390x360-last.png`,
  `tamper-hover-1440.png` 1장.
- 변조: `--control-wash-hover`를 `#ff00ff`로 바꾸면 glass 호버 항목이
  `rgba(127,127,127,.16)` → `rgb(255,0,255)`, **3,973px** 변화.
