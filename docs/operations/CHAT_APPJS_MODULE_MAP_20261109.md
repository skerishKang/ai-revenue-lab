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

## 7. 지도에서 빠져 있던 약 1,700줄의 정체 (2026-11-09 보완)

0단계-B 지도는 구역별 **함수 범위 + 변수 선언 줄**만 세어 8,184줄 중 약 6,450줄만 설명했다.
추출기에 `line_accounting`(함수 밖 최상위 코드 블록·주석·빈 줄·다중 줄 변수 초기화)을 추가해
기준 리비전(app.js 8,184줄)을 다시 세면 다음과 같다. 합은 정확히 8,184줄이다.

| 항목 | 줄 수 | 설명 |
| --- | --- | --- |
| 최상위 함수 본문 | 5,953 | 291개 함수의 시작~끝(내부 주석·빈 줄 포함) |
| 최상위 변수(다중 줄 초기화 포함) | 770 | `const/let` 선언과 이어지는 초기화 줄 |
| 빈 줄 | 247 | 함수 밖 |
| 주석 전용 줄 | 517 | 함수 밖 `//`, `/* */` |
| **함수 밖 최상위 실행 코드** | **697** | 78개 블록. 이벤트 연결·초기화·lazy 블록 |
| 합계 | 8,184 | |

### 7.1 함수 밖 최상위 코드 697줄의 구역별 분포

| 구역 | 블록 | 줄 수 | 성격 |
| --- | --- | --- | --- |
| Claw | 30 | 252 | 폼·커넥터·캘린더 링크·자동화 이벤트 연결 |
| 로그인 세션 | 13 | 198 | 고급 메뉴 버튼 루프, 로그아웃/삭제 확인 리스너 |
| 대화 | 15 | 105 | 컴포저·문서 형식·첨부 트레이 연결 |
| 사이드바 | 3 | 49 | 설정/모바일 메뉴/스크림 리스너, Escape 처리 |
| 설정 | 5 | 43 | 설정 dialog close/cancel/backdrop, 프로필 토글 |
| 공통 | 9 | 24 | 부트스트랩·전역 이벤트 |
| 최근 대화 메뉴 | 1 | 12 | 목록 컨테이너 연결 |
| 유틸 | 1 | 8 | 내보내기/검색 연결 |
| 캘린더 | 1 | 6 | 캘린더 진입 연결 |

큰 블록 예: `4685-4760`(76줄, 로그인/세션 리스너 try), `4627-4683`(57줄, 고급 메뉴 버튼 for),
`4786-4813`(28줄, 설정 dialog click/backdrop), `4763-4783`(21줄, 프로필 토글),
`4541-4560`(20줄, 프로젝트 내비게이션). 이 코드는 함수 본문이 아니므로 지도의 함수 줄 합에
들어가지 않았고, 변수 선언도 아니어서 변수 줄에도 들어가지 않았다. **약 1,700줄 차이의 실체는
다중 줄 변수 초기화(770) + 빈 줄(247) + 주석(517) + 함수 밖 실행 코드(697)**다.

## 8. app.js 클로저 구조와 구역 이동 방식 (CTO 결정)

- `app.js` 전체가 `(() => { "use strict"; ... })()` 하나의 클로저다. 구역 함수는 전역이 아니라
  이 클로저의 `const` DOM 참조·`let` 상태·다른 함수를 직접 참조한다. 파일만 그대로 옮기면
  참조가 끊긴다.
- 새 모듈 파일은 전역 factory 하나만 노출한다:
  `window.PadiemChatSettingsModule = { create(deps) { ...; return {...}; } }`.
  사이드바도 같은 형태(`window.PadiemChatSidebarModule`)다.
- `index.html`은 두 모듈을 `app.js`보다 먼저 일반 `<script>`로 로드한다. release 스탬프는
  index.html의 모든 로컬 script 참조에 `?v=`를 붙이므로 새 파일도 자동으로 대상이다.
- `app.js`에는 같은 이름의 한 줄 전달 함수만 남긴다:
  `function openSettings(...a) { return settingsModule().openSettings(...a); }`.
  함수 선언 끌어올림과 호출부는 그대로다.
- `settingsModule()`/`sidebarModule()`은 첫 호출 때 `create(deps)`를 한 번만 실행하고 캐시한다.
- `deps`는 클로저 변수를 getter로 넘긴다(`get settingsDialog() { return settingsDialog; }`).
  옮긴 함수가 다시 대입하는 `advancedSettingsReturnState`만 setter를 함께 둔다.
  getter는 호출 시점에 읽으므로 **첫 호출 전에 바뀐 값도 반영**된다.
- 옮긴 함수 본문 변경은 `클로저 변수 → deps.x` 기계적 치환만 한다. 함수 이름·DOM id·저장 키·
  이벤트 이름은 바꾸지 않는다. 다른 구역 함수는 옮기지 않는다.
- 최상위 이벤트 연결 줄(예: `settingsButton.addEventListener("click", ...)`, `sidebarCollapseButton?.addEventListener(...)`)은
  **app.js에 남긴다**. 모듈 factory는 첫 호출 때 만들어지므로, 리스너를 모듈로 옮기면 등록
  시점이 바뀌어 동작이 달라진다. 남은 리스너는 전달 함수를 호출한다.

## 9. 최근 대화 메뉴 구역 확정 (R5 3단계, #7216)

이동 대상은 추출기의 구역 분류가 **최근 대화 메뉴**로 놓은 함수 18개(현재 app.js
기준 494줄)다. 분류 규칙(`history|recent|rename|pin|deleteConversation|patchConversation`)에
의해 함께 잡힌 것까지 같은 구역으로 취급한다(§1의 489줄 실측과 같은 집계다).

| 함수 | 현재 줄 범위(app.js 7,928줄 시점) | 비고 |
| --- | --- | --- |
| `renderTyping` | 734-745 | 이름의 `pin`이 분류 규칙에 매칭된 대기 표시(대화 렌더링) |
| `clearHistoryUI` | 1168-1175 | 로그아웃 정리 |
| `renderHistorySkeleton` · `renderHistoryLoadFailed` · `fetchRecentConversations` | 2747-2785 | #6119 스켈레톤·재시도 행 |
| `loadRecentConversations` | 2841-3003 | 목록 렌더 + 이름 변경/고정/삭제 메뉴 + Claw 라벨 보강 |
| `clearHistoryActionStatus` · `showHistoryActionStatus` · `patchConversation` · `focusHistoryConversation` | 3021-3056 | PATCH 2필드(제목·고정) 계약 |
| `beginConversationRename` | 3058-3129 | 제목 길이 상한 `HISTORY_TITLE_MAX_CHARS`(3019) 사용 |
| `deleteConversation` | 3131-3164 | 확인 대화상자 → DELETE |
| `clearClawRunHistoryPdfPreviews` · `setClawRunHistoryStatus` · `clawRunHistoryErrorMessage` | 7463-7488 | Claw 최근 실행 카드 상태/오류 표시 |
| `fetchClawRunHistory` · `loadClawRunHistory` · `syncClawRunHistoryVisibility` | 7688-7776 | Claw 최근 실행 목록(표시 전용) |

- **최상위 연결 코드**: 이 구역의 함수 밖 코드는 `document` click/keydown 리스너
  블록 하나(3004-3015, 목록 컨테이너의 열린 메뉴 닫기·Escape)뿐이다. §8 규칙대로
  **app.js에 그대로 남긴다**(모듈은 첫 호출 때 만들어지므로 리스너 등록 시점이
  달라진다). `clawRunHistoryRefresh`/`clawRunHistoryExpand` 리스너 블록(7778-7791)은
  추출기가 Claw로 분류한 최상위 코드로, 역시 app.js에 남는다.
- **클로저 변수**는 선언 위치를 옮기지 않고 deps로 넘긴다. DOM 참조 18개와
  `HISTORY_TITLE_MAX_CHARS`·`authState`·`authViewEpoch`·`shell`·`input`·`conversationState`·
  `inFlight`·`clawConversationIds`·`clawRunHistoryPdfControllers`는 getter,
  다시 대입하는 `historyReadSequence`·`clawConversationLabelsRead`·
  `clawRunHistoryInFlight`·`clawRunHistoryLeftSurface`·`clawRunHistoryLimit`·
  `clawRunHistoryVisibilityEpoch`·`pendingClawRunFocusId`는 getter+setter.
- 다른 구역 함수(`uiT`·`clawT`·`sidebarActionIcon`·`openSavedConversation`·`readClawRuns`·
  `mappedUiError`·`safeLocalUiMessage`·`failureCodeNote`·`renderClawRunCard`·
  `resetConversationView`·`setNote`·`idleNote`)는 deps getter로 호출한다.
- 결과: `app.js` 7,928 → 7,529줄, 새 파일 `chat-history-module.js`(506줄),
  상한 8,028 → 7,629.

## 10. 로그인 세션 구역 확정 (R5 4단계, #7216)

이동 대상은 추출기의 구역 분류가 **로그인 세션**으로 놓은 함수 41개(현재 app.js
기준 693줄)다. §1 기준 43개·779줄에서 앞 단계 이동으로 분류가 조정되었다.

- 대표: `applyAuthState`(1862-2001), `loadAuthStatus`(2889-2939),
  `submitPasswordChange`(2658-2701), `submitPasswordResetConfirm`(2597-2637),
  `openAuthDialog`(2029-2063), `signOutCurrentAccount`(4242-4260),
  `reviewedGoogleAuthorizationUrl`(6066-6077) — 괄호는 7,529줄 리비전 기준.
- **최상위 연결 코드**: 프로필 패널 생성 대입 블록(244-267)과 로그인/계정 리스너
  블록(2941-2943, 3013-3029, 4263-4279, 4305-4361, 4363-4438, 6587-6598)은
  §8 규칙대로 app.js에 남는다.
- **클로저 변수**: DOM 참조·상수는 getter, 다시 대입하는
  `authState`·`authViewEpoch`·`authDialogView`·`passwordResetToken`·
  `clawApprovalEpoch`·`clawApprovalInFlight`·`clawApprovalSessionToken`·
  `pendingNotificationConversationId`·`pendingNotificationRunId`는 getter+setter.
  deps 113개(getter 113 / 그중 setter 9; 모듈이 읽지 않는 `projects`·
  `resetConversation` getter 2건은 아르곤 지적 반영으로 제거해 115→113).
- 다른 구역 함수는 deps getter로, 옮긴 함수끼리의 호출도 deps(→ app.js 전달 함수
  → 같은 모듈)로 간다. `document`·`window`·`fetch`·`URL` 등 전역은 본문 그대로.
- 결과: `app.js` 7,529 → 7,012줄, 새 파일 `chat-auth-module.js`(747줄),
  상한 7,629 → 7,110(실측 7,010+100; PR 초안의 7,107은 7,007 과소 계수였고
  deps 미사용 getter 2건 제거 뒤 최종개 기준으로 정정). 이전 시험 12파일 +
  신규 계약 2종(`test_r5_step4_auth_module_7216`·`test_r5_step4_auth_browser_7216`).

## 11. 대화 구역 함수 확정 (R5 다음 구역, 대기 중 기록)

다음 이동 대상은 추출기의 구역 분류가 **대화**로 놓은 함수 24개(현재 app.js
7,012줄 기준 1,115줄)다. §1의 25개·1,201줄에서 앞 단계 이동으로 분류가 조정되었다.

- `attachmentCopy`·`showComposerInlineHint`·`updateComposer`(533-597),
  `showConversation`(771-806)·`addUserMessage`(818-899)·`renderAnswer`(954-980),
  `renderStreamError`(1110-1124), 첨부 7개(`clearAttachment`~`attachmentPayload`,
  1150-1339), `safeLocalUiMessage`(1522-1527), `resetConversationView`·
  `resetConversation`(1715-1771), `requestCompletedAnswer`·`applyStreamDone`
  (2601-2686), `requestStreamingAnswer`(2943-3347)·`cancelActiveStream`(3349-3371)·
  `requestAnswer`(3400-3571), `approvalDecisionErrorMessage`(5814-5820)·
  `approvedMemoryErrorMessage`(6311-6320) — 괄호는 7,012줄 리비전 기준.
- **최상위 연결 코드**(app.js 유지 대상): 첨부 트레이/컴포저 리스너(562-572),
  알림 진입(1968-1976), 전송/문서 형식 리스너(2537-2599, 3597-3607, 3726-3729),
  종료 시 정리(6933-6968) 등 13개 블록.
- 클로저 변수: `messageList`·`conversationArtifacts`·`conversationArtifactContext`·
  `cancelStreamButton`·`attachmentButton`·`attachmentChipList`·`composerInlineHint`·
  `NOTIFICATION_CONVERSATION_ID`·`composerForm` — getter는 DOM/상수, 다시 대입되는
  변수는 setter 부여. 이전 시험 후보는 지도 §4의 대화 구역 44개 파일.

