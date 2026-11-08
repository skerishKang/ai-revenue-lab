# CHAT app.js 모듈 지도 (R5 0단계-B, #7216)

작성: 2026-11-09 · 근거: `tools/r5_appjs_map.py` 출력(JSON)만 사용. 코드 이동·기능 변경 없음.
이 문서는 R5 분해의 순서 근거다. 상한 시험은 `apps/padiem-chat/tests/test_r5_file_size_guard_7216.py`(0단계-A).

## 0. 규모 (추출기 실측)

- `static/app.js` 총 **8,184 줄**.
- 최상위 함수 **291**, 최상위 변수 **376**, 함수 간 호출 엣지 **661**.
- `window` 전역 노출 **6**: `PadiemChatConversationOpener`, `PadiemChatProjectOpener`, `PadiemChatRegenerate`, `PadiemChatRouting`, `PadiemSessionPresentation`, `__padiemClawLocalHandoff`.
- DOM id 참조 **258**, `addEventListener` **135**(click 90, submit 10, keydown 5, change 5, input 4, cancel 5 등). 주요 대상: `document`(9), `input`(7), `button`(4), `settingsDialog`(3).

## 1. 기능 구역별 줄 수 · 결합도

줄 수는 최상위 함수 범위 합 + 최상위 변수 줄. 결합도는 구역 간 호출 왕복 합.

| 구역 | 함수 | 줄 수 | 결합도(왕복 호출) | 비고 |
| --- | --- | --- | --- | --- |
| Claw | 95 | 1,928 | 148 | 실행·PC·디바이스·커넥터. 열린 PR #7197 접촉 |
| 공통 | 93 | 1,736 | 282 | 아이콘·uiT·네비·재시도 등 허브. 마지막에 분리 |
| 대화 | 25 | 1,201 | 150 | 스트리밍·메시지·컴포저 |
| 로그인 세션 | 43 | 779 | 71 | `applyAuthState`(1797-1936)·`loadAuthStatus` |
| 최근 대화 메뉴 | 18 | 489 | 53 | `loadRecentConversations`(2816-2978)·rename/pin |
| 캘린더 | 8 | 201 | 23 | Google Calendar 연결·활성화 |
| 사이드바 | 4 | 69 | 13 | 접기·아이콘 |
| 설정 | 5 | 50 | 8 | 고급 설정·등급 |
| 라이브러리 | 0 | 1 | 0 | 이미 `library.js`/`outputs.js`로 모듈화, 잔여 1줄 |
| 유틸 | 0 | 0 | 0 | 이미 `util-*.js`로 모듈화. 열린 PR #7197 진행 중 |

대표 함수 범위: `requestStreamingAnswer`(3678-4082, 대화), `renderClawRunCard`(7758-7941, Claw),
`beginConversationRename`(3033-3104, 최근 대화 메뉴), `setNavActive`(421-513, 공통).

## 2. 구역 간 호출 (상위 엣지)

대화→공통 91 · Claw→공통 47 · 로그인세션→공통 43 · 공통→Claw 36 · 최근대화메뉴→공통 27 ·
공통→대화 21 · 대화→Claw 19 · 캘린더→Claw 14 · 공통→로그인세션 12 · Claw→최근대화메뉴 7.

공통이 허브다. 잎 구역(설정·사이드바·캘린더·최근 대화 메뉴)은 공통 의존은 있어도 역의존이 적어 먼저 분리하기 쉽다.

## 3. index.html 스크립트 로드 순서 (요약)

`theme-init → … → locale → connector-vocabulary → chat-transport → conversation-state →
shared-* → message-lifecycle → auth-session → chat-session → claw-session → calendar →
voice-* → tus-upload → project-file-upload → **app.js** → mobile-header-collapse →
meeting-* → sidebar-section-collapse → claw-home-choices → claw-connection-* →
b66-quote-runtime → product-capabilities → conversation-search → library → outputs →
conversation-export → claw-* → pc-connect-flow → claw-connection-state →
claw-composer-connection-status → util-menu → util-pdfmd …`

app.js는 다수 모듈 뒤·일부 모듈 앞에 로드된다. 분리 시 전역 노출(§0)과 로드 순서 의존을 보존해야 한다.

## 4. app.js 문자열을 검사하는 tests (구역별 파일 수)

총 174개 test 파일이 app.js를 읽는다. 구역별(함수명 매칭) 중복 집계:

| 구역 | 파일 수 | 대표 파일 |
| --- | --- | --- |
| 공통 | 63 | test_2505_chat_claw_conversation_continuity, test_4139_claw_shared_home_parity |
| Claw | 53 | test_3531_claw_general_routing, test_4072_claw_general_history_projection |
| 대화 | 44 | test_2505_chat_claw_attachment_parity, test_4471_conversation_search |
| 로그인 세션 | 18 | test_auth_session_cleanup_r1, test_5481_login_modal |
| 최근 대화 메뉴 | 15 | test_history_list_loading_states_261029, test_claw_session_reopen_ui |
| 설정 | 5 | test_5121_byok_ui, test_b62_1815_mode_presentation |
| 사이드바 | 2 | test_4416_sidebar_profile_shell, test_ui_request_speed_261101 |
| 캘린더 | 2 | test_connectors_bright_calendar_state_ui |

분해 시 이 문자열 검사들이 깨지지 않도록, 해당 구역을 옮길 때 관련 tests를 함께 이동/갱신한다.

## 5. 열린 PR이 건드리는 구역

- **#7197** `feat/util-inapp-tools-7173` — 유틸/Claw 이동. 진행 중 → 유틸·Claw 분해는 보류.
- **#3066** `[HOLD][DEFERRED]` — 활동 없음, 영향 없음.
- (0단계-A #7220는 머지 완료.)

## 6. 옮기는 순서 제안 (호출 적고 열린 PR 없는 구역부터)

1. **라이브러리** — 이미 모듈화, app.js 잔여 1줄 정리(결합 0).
2. **설정** — 결합 8, 줄 50.
3. **사이드바** — 결합 13, 줄 69.
4. **캘린더** — 결합 23, 줄 201.
5. **최근 대화 메뉴** — 결합 53, 줄 489(#7175 직후 안정).
6. 이후 로그인 세션 → 대화 → 공통(허브, 마지막). **Claw/유틸은 #7197 종료 후**.

원칙: 억지로 쪼개지 말고 새 기능은 새 모듈 파일로. 상한 상향 금지(#7216).
