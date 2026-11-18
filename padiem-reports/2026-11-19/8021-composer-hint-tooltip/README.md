# #8021 — 빈 전송 안내·전송 툴팁이 입력창 단추와 겹치지 않게

2026-11-19 눈 점검(#8020~#8024, padiem-reports/2026-11-19/chat-visual-audit)에서
나온 Chat 입력창 문제 2건을 고친 결과물입니다. 캡처는 `before/`(수정 전 main
635a19d657)과 `after/`(이 PR) 5테마 × 1440×900·390×844 입니다.

## 고친 것

1. **빈 메시지 전송 안내가 음성·전송 단추 위에 겹쳐 잘림(불편)**
   - 원인은 두 겹이었습니다.
     - `claw-composer-connection-status.js`의 `syncLayout()`이 안내(`composerInlineHint`)
       에 **인라인 `top`**을 매번 새겨 PC 연결 칩 아래(=단추 줄)에 박아 넣었습니다.
       CSS의 `top: 34px`는 이 인라인 값에 항상 덮여 쓰였습니다.
     - `voice-composer.css`의 기본 자리(`top: 34px`/`30px`) 자체도 단추 줄과 같은 높이였습니다.
   - 수정: 인라인 `top` 새김을 제거하고, 안내는 입력창 **위 한 줄**(상자 바로 위,
     `top: -26px` / 620px 이하 `-24px`, 오른쪽 정렬)로 옮겼습니다. 값만 바꿨고
     색·`!important`는 건드리지 않았습니다.
2. **전송 툴팁이 클릭 뒤에도 남아 입력창과 겹침(보기)**
   - `shared-tooltip.js`:
     - 표시 확정 시(`show`) 예약 타이머를 `hide()`가 함께 지우도록 해, 닫힌 칩이
       예약에 의해 되살아나지 않게 했습니다.
     - 문서 레벨 닫힘을 추가했습니다 — 어디든 누르면 닫힘(터치로 칩 자체를 누를 때는
       기존 탭 토글 유지), 아무 입력 시작에도 즉시 닫힘. 포커스 이동은 기존 blur 경로.
     - 칩 자리 선정에 단추 충돌 회피를 넣었습니다 — 위자리가 단추(PC 연결 상태 칩 등)와
       겹치면 왼쪽·오른쪽으로 비켜난 뒤 아래자리를 순서대로 시도하고, 모두 어렵면
       기존 규칙(위, 화면 밖이면 아래)으로 돌아갑니다. 색·모양은 그대로입니다.

## 겹침 시험

`apps/padiem-chat/tests/browser_composer_hint_tooltip_overlap_8021.py` — 실제
`static/index.html`을 띄워 그려진 상자를 잰다. 5테마 × 1440×900·390×844 = 10케이스:

- 빈 전송 안내가 그려지고, 입력창 안 **모든 단추 상자**와 겹치지 않으며, 화면 안에 온전히 있다.
- 전송 칩(키보드 포커스로 표시)이 **모든 단추 상자**와 겹치지 않는다.
- 입력 시작 → 즉시 닫힘, 밖을 누름 → 즉시 닫힘.

로컬 실행: 신규 시험 10케이스 + 기존 입력창·툴팁 관련 87개 통과
(browser_voice_icons_always_visible_4816, test_r5_step5_conversation_module/browser_7216,
test_b62_composer_pc_connection_status_261020, test_7297_claw_direct_ui,
test_4488_answer_copy_wiring_261019).

## 캡처 대표 비교

| 상태 | 전 | 후 |
|---|---|---|
| 빈 전송 안내(padiem-home 1440×900) | 단추 위에 겹쳐 뒤에 잘림 — `before/before-empty-send-padiem-home-1440x900.jpg` | 입력창 위 한 줄에 온전히 표시 — `after/after-empty-send-padiem-home-1440x900.jpg` |
| 전송 칩(padiem-glass 390×844) | 입력창·단추 위에 남음 — `before/before-send-chip-padiem-glass-390x844.jpg` | 단추와 겹치지 않는 자리(상태 칩 왼쪽) — `after/after-send-chip-padiem-glass-390x844.jpg` |
| Claw 연결 안내(긴 문구) | — | `after/claw-connection-notice-padiem-home-390x844.jpg` (입력창 위 한 줄, 잘림 없음) |

파일명 규칙: `{before|after}-{empty-send|send-chip}-{테마}-{가로}x{세로}.jpg`
