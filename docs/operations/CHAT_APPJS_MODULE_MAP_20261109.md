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


## 12. 대화 구역 확정 (R5 5단계, #7216) — 5a/5b 2개 PR로 분할

대화 구역 24개 함수·1,115줄은 한 PR보다 크므로 §11의 예시(목록·불러오기 /
전송·스트리밍 표시)로 2개로 나눈다.

- **5a 목록·표시·첨부·리셋 19개**(1,046줄 중 본문 약 640줄): `attachmentCopy`·
  `showComposerInlineHint`·`updateComposer`, `showConversation`·`addUserMessage`·
  `renderAnswer`·`renderStreamError`, 첨부 7개(`clearAttachment`~`attachmentPayload`),
  `safeLocalUiMessage`, `resetConversationView`·`resetConversation`,
  `approvalDecisionErrorMessage`·`approvedMemoryErrorMessage`. 동기 DOM/렌더링만 —
  요청 수명·컨트롤러·에포크를 만지지 않음.
- **5b 전송·스트리밍 5개**: `requestCompletedAnswer`·`applyStreamDone`·
  `requestStreamingAnswer`·`cancelActiveStream`·`requestAnswer`. 비동기 요청 수명,
  AbortController·진행 중 요청·에포크 재대입이 집중된 구간이라 5a와 분리.
- 분할 기준: 클로저 재대입(특히 요청/스트리밍 상태)의 유무와 시험 겹침.
  5a는 동기 표시/첨부만, 5b는 전송·스트리밍 변수가 모인 곳.
- 5a 결과: `chat-conversation-module.js`(462줄), `app.js` 7,010 → 6,691줄,
  상한 7,110 → **6,791**. deps getter 68개 · setter 13개(재대입 변수:
  `conversationEpoch` 포함 요청·스트리밍 북키핑). 이전 시험 이전 — 대화
  함수명을 참조하는 40개 파일 중 영향을 받는 25개 + 전체 app.js 실행 하네스
  17개에 모듈 로더 1줄 추가(index.html 순서와 동일). 신규 계약 2종
  (`test_r5_step5_conversation_module_7216` 19함수 vm 동작·getter·setter /
  `test_r5_step5_conversation_browser_7216` 19개 전달 직접 호출 + getter·동작).
  뮤테이션 검증: 본문 복제 → 전달 개수 실패, `deps.` 제거 → moved-bodies 실패.
  전후 스크린샷(1440·390): 목록·새 대화 거의 동일(0.22% 이하), 스트리밍·답변
  차이는 실시간 응답 내용 차이로 레이아웃 동일(blur 평균차 1.3~4.5).
- 5b 결과: `chat-streaming-module.js`(704줄, 5개 함수), `app.js` 6,691 → **6,072줄**,
  상한 6,791 → **6,172**. deps getter 43개 · setter 7개(`activeClawRunId`·
  `activeProject`·`activeRequestArticle`·`activeRequestCancelReason`·
  `activeRequestController`·`inFlight`·`lastCompletedAnswerRequest`). 이전 시험
  55개 파일 이전 + 신규 계약 2종(`test_r5_step5b_streaming_module_7216` 5함수 vm
  동작·getter·setter / `test_r5_step5b_streaming_browser_7216` 5개 전달 직접 호출
  + getter·setter).

## 13. R5 A1 자동화 구역 확정 (2026-11-11)

`docs/operations/R5_app_js_분해_설계_261110.md`의 A1 단계를 5a/5b와 같은 방식
("함수만 이동, 선언·리스너 등록은 app.js 유지")으로 수행했다.

- **chat-automation-module.js(13개·295줄)**: `resetClawAutomationState`·
  `setClawAutomationLoading`·`setClawAutomationError`·`setClawAutomationForbidden`·
  `renderClawAutomationRules`·`loadClawAutomationRules`(규칙 목록·읽기 전용
  카탈로그), `setClawAutomationToggleStatus`·`findRuleToggleButton`·
  `focusRuleToggleAfterReload`·`toggleClawAutomationRule`(토글),
  `mountAutomationView`·`openClawAutomation`·`setClawAutomationRetryVisible`(화면).
- **chat-automation-form-module.js(15개·278줄)**: 편집 8개
  (`setClawAutomationEditStatus`~`submitClawAutomationEdit`), 생성 7개
  (`setClawAutomationCreateStatus`~`submitClawAutomationCreate`).
- **deps**: 자동화 모듈 31(getter)/1(setter: `automationViewMounted`), 폼 모듈
  47(getter)/3(setter: `clawAutomationEditInFlight`·`clawAutomationCreateInFlight`·
  `clawAutomationEditingRuleId`). 모듈 간 경계는 A→B `openClawAutomationEdit`,
  B→A `loadClawAutomationRules` 2개.
- **전달 함수 27개**: deps를 거치는 모듈 내·모듈 간 호출(5b 관례)과 남은 app.js
  참조(리스너·초기화)에 필요한 이름만. 미호출 `focusRuleEditAfterReload`는
  전달 함수 없이 본문째 이동.
- **app.js 줄 수**: 6,123 → 5,765(−358). 상한 시험 5,865(실측+100)로 갱신.
- **선언·리스너는 app.js에 남는다**(R5 B1 동반분): 자동화 선언 블록과
  편집·생성·내비게이션·재시도 리스너 등록, `#padiem-automation` 주소 복원.
- **검증**: 이동 전후 지도 비교 — 사라진 것은 28개 본문뿐이고 남은 app.js에는
  전달 함수 27개와 연결부(`automationModule`·`automationFormModule`·인스턴스
  let 2개)가 새로 생겼다. 리스너 감소 2건(`toggle.click`·`edit.click`)과 DOM id
  감소 4건(`automationView*`)은 이동 본문 안 것이며, 최상위 리스너 등록은 모두
  app.js에 남는다. 부팅 장부(1440·390) 구조 해시·요청 주소가 이동 전과 동일
  (창 이름은 새 모듈 공장 2개가 추가 — 등록 물건). 뮤테이션 확인: 본문을 app.js에
  다시 볼러 넣으면 `test_moved_bodies_live_only_in_the_modules` 실패, 모듈에서
  `deps.`를 지우면 vm 하네스 실패.

## 13-A. R5 B1 시범 — 규칙 보강 4가지 적용 (2026-11-11)

A1에 이어 §3.5 B1을 수행하되, CTO 지시로 보강 4가지를 두 구역에만 시범 적용했다.

- **자동화 구역**: 선언 46개(자동화 DOM 41·상태 let 4·InFlightRules Set 1)를 두
  모듈 create() 안으로, 리스너 등록 10개를 `automationForm.wireEditListeners()`·
  `automationForm.wireCreateListeners()`·`automation.wireViewListeners()`로 —
  app.js의 원래 블록 자리에서 호출해 등록 시점·순서 보존. `clawAutomation`은
  화면 전환 구역도 읽으므로 모듈로 옮기지 않고 컨텍스트 소유로.
- **로컬 PC 연결 패널 구역**: 전체(선언 5개·함수 1개·최상위 코드·리스너 2개·
  창 계약 `__padiemClawLocalHandoff`)를 `chat-local-pc-panel-module.js`(114줄)로.
  창 계약 노출은 wire() 안에서 원래 시점 유지.
- **보강 (다) — 공유 상태 한 파일**: `chat-app-context.js`(37줄) 신설. 이 두
  구역이 함께 쓰는 `clawAutomation`·`clawAutomationList`를 소유하고(app.js 시작
  시점 조회 — 기존 선언 위치와 같은 틱), app.js는 `authState`·`shell`·
  `clawWorkspace`와 공유 함수들(`uiT`·`setNavActive`·`closeSidebar`·
  `clearClawWait`·`syncClawRunHistoryVisibility`)을 라이브 접근자로 올린다.
  소유권 이전 자체는 B6으로 남긴다(다른 14곳이 authState를 읽으므로).
- **보강 (라) — 등록부**: 한 줄 전달 함수 27개를 제거하고 모듈 API를 컨텍스트에
  평탄 등록(`app.provide("automation"|"automationForm"|"localPcPanel")`, 중복
  등록·이름 충돌 시 예외). 남은 app.js는 `app.openClawAutomation()` 등 등록부
  경로로 호출. 모듈 간 경계 2개(A→B `openClawAutomationEdit`, B→A
  `loadClawAutomationRules`)도 평탄화된 컨텍스트로 해결.
- **create()는 deps를 읽지 않는다**: 선언이 create() 안으로 들어갔으므로
  엄격 빈 deps로 create()만 불러도 예외가 없다(계약 시험 첫 검사).
- **app.js 줄 수**: 5,768 → 5,429(−339). 상한 5,865 유지(여유 436).
- **검증**: 지도 비교 — 사라진 함수 30(전달 27 + 연결 2 + 패널 함수 1), 사라진
  최상위 변수 51(자동화 46 + 패널 5), 사라진 리스너 12(자동화 10 + 패널 2, 모두
  모듈 wire로 이동), 신규 변수 4(`app`·`automation`·`automationForm`·
  `localPcPanel`). 부팅 장부(3회×2폭): 구조 해시·요청 주소 동일, 리스너
  다중집합 동일(1440의 ±1 DOMContentLoaded 레이스는 main에 이미 있던 것 —
  base run1 vs run2 차이로 확인), 창 이름은 `PadiemChatAppContext`·
  `PadiemChatLocalPcPanelModule` 2개 추가(등록 물건). 뮤테이션: 본문 재복제·
  deps. 제거 모두 실패.

## 13-B. R5 A2 기억·실행 기록 구역 확정 — 보강 4가지 통째 적용 (2026-11-11)

B1 시범(`#7439`)에서 확정한 보강 4가지를 설계 문서 §3.4 A2 + §3.5 B2 동반분 전체에 그대로 적용했다.

- **chat-memory-module.js(12개 함수 + wire 2개 · 380줄)**:
  - 함수 12개: `setApprovedMemoryStatus`·`renderMemoryProposalReview`·`proposalBody`·`approveProposal`·`rejectProposal`·`renderApprovedMemoryCard`·`renderApprovedMemoryDetail`·`fetchApprovedMemoryList`·`loadApprovedMemoryList`·`loadMoreApprovedMemories`·`loadApprovedMemoryDetail`·`syncApprovedMemoryVisibility`.
  - 보강 (가) 자체 선언 8개: `clawApprovedMemory`·`clawApprovedDisclosure`·`clawApprovedRefresh`·`clawApprovedLoading`·`clawApprovedError`·`clawApprovedList`·`clawApprovedEmpty` + `approvedMemoryInFlight`.
  - 보강 (나) 연결 2개: `wireMemoryListeners()`(`clawApprovedRefresh` 클릭 리스너)와 `wireMemoryReviewContract()`(`window.PadiemChatMemoryReview` 창 계약)를 원래 app.js 위치에서 호출.
- **chat-run-history-module.js(4개 함수 + wire 1개 · 303줄)**:
  - 함수 4개: `invalidateClawRunsRead`·`readClawRuns`(실행 목록 단기 읽기 캐시), `clawRunStatusLabel`·`renderClawRunCard`(실행 기록 카드).
  - 보강 (가) 자체 선언 5개: `CLAW_RUNS_READ_WINDOW_MS`·`emptyClawRunsRead`·`clawRunsRead` + `clawRunHistoryRefresh`·`clawRunHistoryFilter`.
  - 보강 (나) 연결 1개: `wireRunHistoryListeners()`(`clawRunHistoryFilter`·`clawRunHistoryRefresh`·`clawRunHistoryExpand` 클릭 리스너 3개 + `window.__padiemClawRunHistoryIncludeGeneral` 토글)를 원래 app.js 위치에서 호출.
- **보강 (다) 공유 문맥(`chat-app-context.js`, 42줄)**:
  - 구역 간 공유 DOM 3개(`clawMemoryReview`·`clawRunHistory`·`clawRunHistoryExpand`)를 컨텍스트 소유로 추가.
  - app.js 소유 공유 항목(`emptyState`·`clawT`·`mappedUiError`·`approvedMemoryErrorMessage`·`safeLocalUiMessage`·`failureCodeNote`·`openSavedConversation`·`downloadClawArtifact`·`setClawRunHistoryStatus`·`clawRunHistoryPdfControllers`·`renderClawApprovalControls`·`loadClawRunHistory`·`clawRunHistoryInFlight` + getter/setter `clawRunHistoryLimit`)을 라이브 접근자로 마운트.
- **보강 (라) 등록부(`app.provide`)**:
  - 한 줄 전달 함수 0개. `app.provide("memory", ...)`·`app.provide("runHistory", ...)`로 등록하고 `historyModule`·`authModule`·`streamingModule` 및 남은 app.js 호출부 6곳은 `app.*` 경로로 호출.
- **app.js 줄 수 및 상한**: **5,441 → 4,843(−598)** (이동 시작점 `26c8a323a5` 기준 5,439 → 4,841, 최신 `main` `ea780fc850` 병합 +2줄 반영). `test_r5_file_size_guard_7216.py` 상한 **5,865 → 4,943**(실측 4,843 + 100).
- **검증**: 지도 비교 — 사라진 함수 16개, 사라진 최상위 변수 16개, 신규 변수 2개(`memory`·`runHistory`), 신규 전달 함수 0개. 부팅 장부(1440·390): 요청 주소 해시·리스너 다중집합 해시 전후 동일, 창 이름 2개(`PadiemChatMemoryModule`·`PadiemChatRunHistoryModule`) 추가. 신규 계약 2종(`test_r5_a2_memory_run_history_module_7216`·`test_r5_a2_memory_run_history_browser_7216`) + 기존 문자열·슬라이스 시험 19파일 이전 + 뮤테이션 2종 적발 확인.

## 13-C. R5 A9 앱 연결(커넥터) 구역 확정 (2026-11-15)

`docs/operations/R5_app_js_분해_설계_261110.md`의 A9 단계를 수행했다. 커넥터
화면 본문을 `chat-connectors-module.js`로 옮겼다.

- **chat-connectors-module.js(23함수 + wire 1개 · 425줄)**: `setConnectorCopy`·
  `connectorSupportKey`·`connectorWorkspaceKey`·`connectorUnavailableCopyKeys`·
  `liveConnectorCards`·`googleDriveConnectButton`·`googleDriveCard`·
  `gmailConnectButton`·`driveConnectOffered`·`syncGoogleDriveConnectButton`·
  `connectorTicketErrorKey`·`~beginGoogleDriveConnect`·`syncGmailConnectButton`·
  `~beginGmailConnect`·`setConnectorCardsLoading`·`setConnectorCardsUnavailable`·
  `renderConnectorStatus`·`~loadConnectorStatus`·`connectorsScope`·
  `mountConnectorsView`·`openConnectorsView`·`openConnectorsDialog`·
  `closeConnectorsDialog`. 설계 문서 A9 카드의 22개 함수에
  `connectorTicketErrorKey` 1개가 더해졌다(#7088 지메일 연결 해제에서 추가된
  도우미).
- **deps 26(getter)/4(setter)**: setter는 다시 대입하는 상태 4개
  (`googleConnectorConnectInFlight`·`googleCalendarReadActivationAfterConnectReturn`·
  `connectorStatusInFlight`·`connectorsViewMounted`)뿐이다.
  `connectorsViewMounted` let 선언은 §8 규칙대로 app.js에 남는다.
- **app.js에 남는 것**: 커넥터 선언(DOM 참조·연결 상수·in-flight let), OAuth
  복귀 처리 블록, 한 줄 전달 함수 5개(`setConnectorCopy`·
  `connectorTicketErrorKey`·`connectorsScope`·`openConnectorsView`·
  `openConnectorsDialog`). 리스너 등록 10개는 모듈 `wireConnectorsListeners()`로
  옮기고 app.js가 원래 블록 자리에서 1회 호출해 등록 시점·순서를 보존한다
  (§13-A 보강 (나) 방식).
- **index.html**: `chat-core-module.js` 뒤·`app.js` 앞에 script 1줄 추가.
- **app.js 줄 수**: 3,630 → 3,265(−365). 상한 3,730 → 3,365(실측+100).
- **시험**: 깨진 선언 글자 고정 계약을 동작 검사로 전환했다(삭제·skip·완화 0).
  `test_b54_connectors_surface_truthful.py`는 14개 시험 이름을 유지하면서 문자열
  절단 대신 실제 모듈 소스를 Node에서 실행(window 스텁 + 엄격 deps, HTML 싱크는
  쓰는 순간 예외)해 요청 목록·응답 가드·안전 싱크·상태 어휘 폐쇄를 행위로
  단정한다. 마크업·locale·CSS 정적 계약 8파일은 소스 단정을 유지하되 읽는 대상을
  모듈로 바꾸고, app.js 쪽에는 wire 호출 1회·모듈이 app.js보다 먼저 로드됨
  단정을 더했다: `test_7365_sidebar_groups`·`test_7368_connector_status_retry`·
  `test_b62_ui_polish_auth_contrast_261108`·`test_chat_claw_answer_views_261015`·
  `test_claw_connector_management_261015`·`test_claw_drive_first_use_261015`·
  `test_connectors_bright_calendar_state_ui`·`test_google_drive_connect_handoff`.
  신규 브라우저 계약 1종 `test_r5_a9_connectors_browser_7216.py` — 실제
  Chromium에서 네비 클릭 1회로 독립 커넥터 화면 전환, 마운트 가드(그리드 1개),
  열 때마다 상태 1회 재판정, 390 폭 접힌 사이드바 리스너 경로, 콘솔·페이지
  오류 0건.
- **검증**: 부팅 장부(1440·390) 구조 해시·요청 주소·리스너 다중집합이 이동 전과
  동일, 창 이름은 `PadiemChatConnectorsModule` 1개 추가. 화면 전후 6화면
  byte-identical, 8px bbox 차이 1건은 같은 빌드 안에서도 재현되는 글꼴 래스터
  비결정성(같은 빌드 재촬영으로 확인, 이동과 무관). 머지·배포 없음.

## 13. R5 다음 구역 후보 조사 (대기 중 기록 — Claw 제외)

> 2026-11-11: 이 절은 `docs/operations/R5_app_js_분해_설계_261110.md`가 대체한다.
> 다음 구역 계획·위험 목록·0단계(시험·CI 기반)는 그 문서를 기준으로 한다.

Claw는 열린 PR #7197 정리 뒤로 제외. 공통 구역(77개 함수·1,388줄)은 허브라
한 번에 옮기지 않고 씨(cluster)로 나누는 것이 후보. 씨 목록은 추출기
`top_level_functions`의 `area == "공통"` 기준이다.

| 후보 씨 | 함수 수(대략) | 비고 |
|---|---|---|
| 프로젝트 파일·대화 | 17 | `loadProjects`·`projectById`·`ensureProject`·`addProjectFile`·`saveProject`·`deleteProject`·`selectProject` 등 |
| Android 핸드오프 | 11 | `readStoredAndroidHandoff`·`claimAndroidHandoff`·`pollAndroidHandoff`·`startAndroidHandoff` 등 |
| 승인·메모리 카드 | 15 | `applyImmediateApprovalDecision`·`approveProposal`·`renderApprovedMemoryCard` 등 |
| 오류·재시도 표면 | 14 | `buildRetryBox`·`renderError`·`renderCancelled`·`lifecycleForError`·`formatBytes` 등 |
| 잔여 허브 | 20 | `setNavActive`(93줄)·`addAssistantShell`·`renderWebGroundingNotice`·룰편집·Gmail 연결 등. 마지막 |

- 이 중 오류·재시도 표면(14)은 대화·스트리밍 추후 단계와 접촉이 많아
  5b 이후에 이어 붙는 자연 후보로 보인다. 나머지는 각 씨의 호출 엣지를
  추출기로 세어 순서 확정 후 진행한다(조사 기록만).

## 13-D. R5 A10 화면 전환 구역 확정 (2026-11-16)

`R5_app_js_분해_설계_261110.md`의 A10 카드 가운데 화면 전환(chat-nav) 절반을
수행했다. A10 남은 절반은 대화 진입(chat-entry: 보내기·저장 대화 열기·다시
생성·입력창 리스너)이다.

- **선정 근거**: 남은 구역 중 외부 의존이 가장 적다. 현재 app.js 기준 측정 —
  밖으로 참조하는 최상위 이름 4개(`uiT`·`syncComposerForClaw`·`closeSidebar`·
  `syncClawRunHistoryVisibility`)가 전부 이미 분리된 모듈 소속이고, 이동하지
  않은 구역에 대한 의존 0, 공유 상태 쓰기 0. 오류·다시 시도(프로젝트
  `activeProject` 쓰기)·대화 진입(프로젝트 3곳 의존)·프로젝트(uiT 11곳 의존)와
  비교. 다른 레인 구역(의견 창·프로필 메뉴·답변 렌더러·로그인 진입)은 피했다.
- **chat-nav-module.js(8함수 + wire 2개 · 236줄)**: `pageViewFor`·`syncRouteHash`·
  `setNavActive`·`switchConversationProduct`·`openClawWorkspace`·
  `openChatWorkspace`(A10 카드 7함수에 상호 맞물린 쌍 1개 추가)·`openClawManual`·
  `openClawRunTarget` + `wireNavRouteListener`(padiem:calendar-open-link)·
  `wireNavEntryListeners`(clawNavButton·padiem:meeting-open·clawManualEntryButton).
- **deps 29(getter)/3(setter)**: setter는 `conversationProduct`·
  `clawArtifactShownFor`·`pendingClawRunFocusId`. 선언(라우트 해시 표·
  PAGE_VIEWS·상태 let)은 §8 규칙대로 app.js에 남는다.
- **app.js에 남는 것**: 선언 전부, 창 공개 계약 2종(`PadiemChatRouting`·
  `PadiemAppSwitch` — 로드 시점 보존), 한 줄 전달 함수 7개, wire 호출 2회(각각
  원래 리스너 블록 자리). `create()`는 deps를 읽지 않는다.
- **app.js 줄 수**: 3,261 → 3,119(−142). 상한 3,365 → 3,216(실측+100).
- **시험**: 신규 `test_r5_a10_nav_module_7216.py` — 구조 계약(로드 순서·전달
  함수·factory·wire 2회·창 계약 2종·모듈 500줄 이하·deps 폐쇄면) + Node vm
  동작 시험(strict deps, 실제 PAGE_VIEWS·라우트 해시 표를 app.js 소스에서
  추출해 주입). 정적 계약 13파일은 기준을 낮추지 않고 읽는 대상만 모듈로
  바꿨다: `test_chat_screen_polish_261103`·`test_4422_sidebar_mode_profile`·
  `test_4862_claw_route_refresh`·`test_3531_claw_general_routing`·
  `test_4765_claw_manual_entry_visibility`·`test_calendar_ui`·
  `test_b54_claw_result_action_truthful`·`test_4647_latest_sidebar_integration`·
  `test_b62_2299_claw_mvp_usability`·`test_continuous_first_turn_layout_261015`·
  `test_connectors_bright_calendar_state_ui`·
  `test_b54_claw_general_route_ordering`(하니스가 switchConversationProduct를
  NAV_SOURCE에서 deps 스트립으로 추출). R-01 도우미 사용 시험은 자동 따라감.
- **뮤테이션 적발 확인**: (a) 이동 본문을 app.js에 되살리기 → 구조 계약 실패.
  (b) 모듈 `pageViewFor` 폴백 변형(home→claw) → vm 동작 시험 실패. 각 원복.
- **보존 확인**: 이동 본문 8개는 deps 접두사·들여쓰기(+4)를 제외하면 원본과
  문자 단위 동일(기계 검증). 인덱스에서 chat-nav-module.js가 app.js보다 먼저
  로드된다.

## 14. T2 현황표(B2-0) — 모듈 연결부별 자기 선언·리스너·deps 분류 (2026-11-16)

#7812 B2-0 카드(제품 코드 0줄). `tools/r5_appjs_map.py --modules` 로 쟀다(0-4: 한 줄 전달 함수
인식을 이 PR에서 도구에 넣었다 — 아래 도구 수정 참조). 기준: main `2fa4ca7`(A10 머지)의 app.js 3,119줄.
측정 방법: 모듈 연결부(`window.PadiemChat…Module.create({…})` 15개, 공유 문맥 `PadiemChatAppContext` 제외)의
deps 항목마다 참조 영역을 찾아 귀속시킨다 — 참조가 전부 그 모듈의 리스너·전달 함수·wire 호출·자기 선언 체인이면
"자기 것"(선언을 모듈 `create()` 로 옮기면 deps 항목이 없어진다), 다른 모듈도 만지면 "공유"(B6),
앱.js 에 선언이 없는 모듈 함수면 "모듈 API"(B7 등록부). deps 개수는 이름 기준(get+set 쌍 1개).
B2 카드 순서(위 → 아래)대로 쓴다. 리스너 블록: 7모듈 모두 app.js 에 남은 자기 리스너 블록이 0개다
(A9·A10·B1 이 이미 wire() 로 옮겼거나 원래 없었다) — 그래서 (나)는 "없음"이고 wire 호출 줄만 남는다.
전달 함수: 모듈 전용(자기 리스너만 부르는) 것이 0개다 — B2(선언·리스너 이동)로는 전달 함수가 줄지
않고, 등록부(B7)에서 0이 된다.

| 모듈(B2 카드) | (가) 자기 선언 | (나) 리스너 블록 | (다) deps 자기/공유/모듈API | (라) 전용 전달 함수 | 예상 감소(줄) |
|---|---|---|---|---|---:|
| PcRun (PcRun) | 2개: `resolvedPcRuns(2063–2063)`, `pcResultRecovery(2067–2069)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 2/4/10 | 없음 | 6 |
| AndroidHandoff (PcRun + AndroidHandoff) | 12개: `androidHandoffPanel(559–559)`, `androidHandoffCode(560–560)`, `androidHandoffNote(561–561)`, `androidHandoffOpen(562–562)`, `androidHandoffCopy(563–563)`, `androidHandoffCopied(564–564)`, `androidHandoffCancel(565–565)`, `androidHandoffError(566–566)`, `ANDROID_HANDOFF_POLL_MS(749–749)`, `androidHandoffTimer(751–751)`, `androidHandoffClaiming(752–752)`, `androidHandoffStarting(753–753)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 12/2/5 | 없음 | 24 |
| Connectors (Connectors) | 12개: `connectorsNavButton(2816–2816)`, `connectorsDialog(2817–2817)`, `connectorsDialogClose(2818–2818)`, `connectorsLoading(2819–2819)`, `connectorsRetry(2821–2821)`, `GOOGLE_DRIVE_CONNECTOR(2825–2825)`, `GOOGLE_DRIVE_TICKET_ENDPOINT(2826–2826)`, `GOOGLE_GMAIL_CONNECTOR(2829–2829)`, `GOOGLE_GMAIL_TICKET_ENDPOINT(2830–2830)`, `CONNECTOR_STATUS_IDS(2833–2839)`, `connectorStatusInFlight(2840–2840)`, `connectorsViewMounted(2856–2856)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 12/5/9 | 없음 | 30 |
| ClawStatus (ClawStatus + ClawForm) | 9개: `clawGenerateBtn(2494–2494)`, `clawRetryCopy(2501–2501)`, `clawWait(2512–2512)`, `clawRetrySeconds(2517–2517)`, `clawRetryTimer(2518–2518)`, `clawUncertainKeys(2525–2525)`, `clawWaitTimer(2529–2529)`, `clawWaitRevealed(2530–2530)`, `clawWaitAnnouncedStage(2531–2531)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 9/16/3 | 없음 | 18 |
| ClawForm (ClawStatus + ClawForm) | 0개: 없음 | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 0/14/10 | 없음 | 0 |
| ClawRun (ClawRun) | 8개: `clawResultKind(2493–2493)`, `clawApprovalActions(2498–2498)`, `clawRequestEcho(2504–2504)`, `clawRequestEchoText(2505–2505)`, `clawArtifactMeta(2506–2506)`, `clawArtifactName(2507–2507)`, `clawArtifactSize(2508–2508)`, `clawResultSuccessNote(2509–2509)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 8/17/21 | 없음 | 16 |
| Nav (Nav(A10)) | 5개: `PANEL_ROUTE_HASH_BY_STATE(802–807)`, `OWNED_PANEL_HASHES(808–808)`, `PAGE_VIEWS(818–829)`, `PAGE_VIEW_BY_ID(830–832)`, `clawNavButton(2477–2477)` | 없음(A9·A10·B1에서 wire 이동/원래 없음) | 5/20/6 | 없음 | 28 |

**합계**: 자기 선언 48개 (74줄), 자기 deps 48개, 리스너 블록 0개, 전용 전달 함수 0개 —
**B2 로 줄어드는 app.js ≈ 122줄**(선언 74 + 자기 deps 항목 48).
7모듈 deps 항목 합계: 자기 48 / 공유 78 / 모듈 API 64 —
공유는 B6(공유 문맥), 모듈 API 는 B7(등록부)에서 없어진다.

### 모듈별 자기 deps 항목(자기 것 — 선언을 옮기면 없어짐)

- **PcRun** (연결부 471–488):
  - 자기 deps(2): `pcResultRecovery`, `resolvedPcRuns`
  - 공유 deps(4): `MESSAGE_LIFECYCLE`, `authState`, `conversationProduct`, `conversationState`
  - 모듈 API deps(10): `findUnfinishedPcRun`, `idleNote`, `loadRecentConversations`, `openSavedConversation`, `pcWaitElapsed`, `renderStoredPcAnswer`, `renderStreamError`, `setNote`, `showPcRuntimeStatus`, `uiT`
- **AndroidHandoff** (연결부 1704–1728):
  - 자기 deps(12): `ANDROID_HANDOFF_POLL_MS`, `androidHandoffCancel`, `androidHandoffClaiming`, `androidHandoffCode`, `androidHandoffCopied`, `androidHandoffCopy`, `androidHandoffError`, `androidHandoffNote`, `androidHandoffOpen`, `androidHandoffPanel`, `androidHandoffStarting`, `androidHandoffTimer`
  - 공유 deps(2): `androidHandoff`, `authState`
  - 모듈 API deps(5): `closeAuthDialog`, `loadAuthStatus`, `setAuthFormError`, `storeAndroidHandoff`, `uiT`
- **Connectors** (연결부 2859–2890):
  - 자기 deps(12): `CONNECTOR_STATUS_IDS`, `GOOGLE_DRIVE_CONNECTOR`, `GOOGLE_DRIVE_TICKET_ENDPOINT`, `GOOGLE_GMAIL_CONNECTOR`, `GOOGLE_GMAIL_TICKET_ENDPOINT`, `connectorStatusInFlight`, `connectorsDialog`, `connectorsDialogClose`, `connectorsLoading`, `connectorsNavButton`, `connectorsRetry`, `connectorsViewMounted`
  - 공유 deps(5): `authState`, `connectorsError`, `googleCalendarReadActivationAfterConnectReturn`, `googleConnectorConnectInFlight`, `shell`
  - 모듈 API deps(9): `activateGoogleCalendarRead`, `beginGoogleCalendarConnect`, `closeSidebar`, `googleCalendarConnectButton`, `openAuthDialog`, `reviewedGoogleAuthorizationUrl`, `setNavActive`, `syncGoogleCalendarConnectButton`, `uiT`
- **ClawStatus** (연결부 2622–2658):
  - 자기 deps(9): `clawGenerateBtn`, `clawRetryCopy`, `clawRetrySeconds`, `clawRetryTimer`, `clawUncertainKeys`, `clawWait`, `clawWaitAnnouncedStage`, `clawWaitRevealed`, `clawWaitTimer`
  - 공유 deps(16): `clawAction`, `clawChannel`, `clawExecuteButton`, `clawInFlight`, `clawLastDispatchKey`, `clawResultArea`, `clawRetryBox`, `clawRetryButton`, `clawRetryHint`, `clawSender`, `clawStatus`, `clawWaitStartedAt`, `clawWorkspace`, `conversationState`, `input`, `shell`
  - 모듈 API deps(3): `clawT`, `localeOr`, `selectedProductTier`
- **ClawForm** (연결부 2767–2792):
  - 공유 deps(14): `app`, `clawAction`, `clawChannel`, `clawExecuteButton`, `clawInFlight`, `clawManualForm`, `clawResultCard`, `clawResultDocx`, `clawResultEmpty`, `clawResultHint`, `clawResultPreview`, `clawRetryButton`, `clawSender`, `input`
  - 모듈 API deps(10): `clawT`, `clearClawArtifact`, `downloadClawArtifact`, `noteClawContentEdited`, `renderClawRequestEcho`, `revealClawCard`, `runClawExecution`, `setClawAreaState`, `setClawButtonsBusy`, `setClawStatus`
- **ClawRun** (연결부 2692–2740):
  - 자기 deps(8): `clawApprovalActions`, `clawArtifactMeta`, `clawArtifactName`, `clawArtifactSize`, `clawRequestEcho`, `clawRequestEchoText`, `clawResultKind`, `clawResultSuccessNote`
  - 공유 deps(17): `PRODUCT_CLAW`, `app`, `authState`, `chatTransport`, `clawApprovalEpoch`, `clawApprovalInFlight`, `clawExecuteButton`, `clawInFlight`, `clawLastDispatchKey`, `clawResultBadge`, `clawResultCard`, `clawResultDocx`, `clawResultEmpty`, `clawResultHint`, `clawResultPreview`, `conversationState`, `input`
  - 모듈 API deps(21): `approvalDecisionErrorMessage`, `beginClawRetryCooldown`, `beginClawWait`, `clawBoundedRefusalCopy`, `clawCurrentDispatchIsUncertain`, `clawExecuteWireKey`, `clawRetryAfterFromResponse`, `clawRetryRemaining`, `clawT`, `clawVisibleExecutePayload`, `clearClawRecovery`, `clearClawWait`, `failureCodeNote`, `isAmbiguousClawFailure`, `loadClawRunHistory`, `mappedUiError`, `safeLocalUiMessage`, `setClawAreaState`, `setClawButtonsBusy`, `setClawStatus`, `showClawAmbiguousRecoveryHint`
- **Nav** (연결부 842–876):
  - 자기 deps(5): `OWNED_PANEL_HASHES`, `PAGE_VIEWS`, `PAGE_VIEW_BY_ID`, `PANEL_ROUTE_HASH_BY_STATE`, `clawNavButton`
  - 공유 deps(20): `AUTOMATION_ROUTE_HASH`, `CLAW_ROUTE_HASH`, `CONNECTORS_ROUTE_HASH`, `PRODUCT_CHAT`, `PRODUCT_CLAW`, `app`, `authState`, `automationDestinationReady`, `clawArtifactShownFor`, `clawManualForm`, `clawResultArea`, `clawWorkspace`, `conversationArtifactContext`, `conversationProduct`, `conversationState`, `emptyState`, `input`, `messageList`, `pendingClawRunFocusId`, `shell`
  - 모듈 API deps(6): `closeSidebar`, `downloadClawArtifact`, `openSavedConversation`, `syncClawRunHistoryVisibility`, `syncComposerForClaw`, `uiT`

### 도구 수정(이 PR 포함 — 설계 §3.3 0-4)

- `tools/r5_appjs_map.py` 에 `--modules` 모드를 추가했다. 0-4(R-18)대로 한 줄 전달 함수를
  인식한다: `function X(...a) { return 공장().X(...a); }` 한 줄을 전달 함수로 읽고 그 공장으로
  모듈을 매긴다. 식별자 대조는 주석을 걷어낸 코드로 한다(연결부 위·아래의 설명 주석이
  참조로 잘못 잡히는 것을 막는다). 최상위 코드 런은 소모된(consumed) 줄에서 끊는다(선언·함수
  본문을 코드 런이 삼켜 귀속이 섞이는 것을 막는다). 창 공개 계약 줄(`PadiemChatRouting`·
`PadiemAppSwitch`)과 wire 호출 줄은 그 모듈의 코드로 귀속된다. 기본 모드(구역 요약)는 그대로다.

### B2 진행과 #7812 완료 기준

- B2 카드 5개(PcRun+AndroidHandoff → Connectors → ClawStatus+ClawForm → ClawRun → Nav)를
  이 순서대로 PR 5개로 진행한다(카드당 PR 1~2개 규칙, ClawForm 은 자기 것이 없어 Connectors·
  ClawStatus PR 에 동행한다). 각 PR 후 `appjs_lines` ≈ 3,119 − 126 ≈ 2,993.
- 완료 기준(`appjs_lines` 300 이하 · 전달 함수 0 · deps 0)은 B3(14줄)·B4(≈102줄)·B5(≈103줄)·
  B6(공유 147줄 + 반복 getter)·B7(연결부·전달 함수 ≈650줄)까지 이어진다. 이 표는 그 길의
  B2 구간 출발점이다.

### B2-1 진행 — PcRun + Connectors 자기 선언 이동 (2026-11-16)

- **대상**: PcRun(자기 선언 2: `resolvedPcRuns`·`pcResultRecovery`, deps 자기 2) + Connectors(자기 선언 12: 커넥터 DOM 5·Drive/Gmail 상수·엔드포인트 4·`CONNECTOR_STATUS_IDS`·`connectorStatusInFlight`·`connectorsViewMounted`, deps 자기 12→항목 14). AndroidHandoff 는 대표 결정으로 보류(안드로이드 작업 때).
- **방식**: 자기 선언을 각 모듈 `create()` 안으로(보강 1). 모듈은 원래 선언 자리에서 즉시 생성(`create({...})` — lazy 헬퍼 제거), `create()` 는 deps 를 읽지 않는다. deps 는 자기 것 16개 항목(14 Connectors + 2 PcRun)이 빠졌다.
- **app.js**: 3,113 → 3,059(−54: 선언 30줄 이동 + 팩토리 축소). `appjs_deps_total` 546 → 530, `appjs_dom_lookups` 201 → 195. `appjs_forwarders` 174·`appjs_function_decls` 233·`appjs_listeners` 83 불변.
- **래칫 기준선**: `structure_baseline.json` 3키 실측 하향 — `appjs_lines` 3113 → 3063, `appjs_dom_lookups` 201 → 195, `appjs_deps_total` 546 → 530(감사 도구 실측; 래칫 시험 통과).
- **시험**: `test_r5_a3_pc_run_module_7216.py`·`test_r5_a9_connectors_module_7216.py` 갱신(deps 축소 반영 + 자기 선언 마커 추가, vm 하니스는 창 스텁의 `PadiemChatPcRecovery.create` 경유로 전환). 파급 정적 계약 13파일 전환(읽는 대상만 모듈로): `test_3933`·`test_5608`·`test_b54_claw_run_history_copy_truthful`·`test_b62_glass_home_chat_parity_261021`·`test_chat_claw_answer_views`·`test_claw_workspace_ui`·`test_r5_a1_automation_module`·`test_5015_chat_pc_recovery_wiring`·`test_5015_general_run_result_lookup`·`test_google_drive_connect_handoff`·`test_5895_pc_long_wait_progress_wiring`·`test_b54_connectors_surface_truthful`(레지스트리에 이동 엘리먼트 5종 등록)·`test_5015_chat_pc_recovery_wiring`. 행동 단정은 유지 — resolved 멤버십 단정은 dedup 행동 단정으로 전환(약화 아님).
- **뮤테이션 적발 확인**: (a) 이동 본문을 app.js에 되살리기 → 구조 계약 실패. (b) 모듈 `pageViewFor` 폴백 변형(home→claw) → vm 동작 시험 실패. 각 원복.
- **초기 화면 장부**: `tools/r5_boot_ledger.py` 1440·390 — 로컬 장부는 같은 트리 재실행에서도 비결정적(390 폭에서 body_structure_hash·window_names·initial_requests 까지 변동; 이동 무관 환경 요인). 1440 리스너 **멀티셋**은 이동 전후 동일(순서만 재실행마다 변동). 장부 동일성 증명은 CI 환경에서 확인한다.
- **동작·문구·DOM 변경 0**: 이동 본문은 deps 접두사와 들여쓰기(+4)만 바뀌고 문자는 동일(기계 검증). create() 즉시 생성으로 DOM 조회 시점이 원래 선언 자리와 같다.

### B2-2 진행 — ClawStatus 자기 선언 이동 (2026-11-16)

- **대상**: ClawStatus(자기 선언 9: DOM 3 `clawGenerateBtn`·`clawRetryCopy`·`clawWait`, 상태 6 `clawRetrySeconds`·`clawRetryTimer`·`clawUncertainKeys`·`clawWaitTimer`·`clawWaitRevealed`·`clawWaitAnnouncedStage`; deps 자기 9→항목 14). ClawForm 은 자기 선언 0·자기 리스너 0으로 옮길 것이 없어 이번 카드에 동행만 한다. AndroidHandoff 는 대표 결정으로 보류(안드로이드 작업 때).
- **방식**: 자기 선언을 모듈 `create()` 안으로(보강 1). 모듈은 원래 선언 자리에서 즉시 생성(`create({...})` — lazy 헬퍼 제거), `create()` 는 deps 를 읽지 않는다. 자기 리스너 블록이 0개여서 `wire()` 이동은 없다(보강 2는 해당 없음). deps 에서 자기 것 14개 항목(9 이름: getter 9 + setter 5)이 빠졌다 — 35→21항목(getter 28→19, setter 7→2).
- **app.js**: 3,063 → 3,032(−31: 자기 선언 9줄·주석 7줄 이동, 팩토리 축소 42줄, 생성 블록 27줄). `appjs_deps_total` 530 → 516, `appjs_dom_lookups` 195 → 192. `appjs_forwarders` 174·`appjs_function_decls` 233·`appjs_listeners` 83 불변.
- **래칫 기준선**: `structure_baseline.json` 3키 실측 하향 — `appjs_lines` 3063 → 3032, `appjs_deps_total` 530 → 516, `appjs_dom_lookups` 195 → 192(감사 도구 실측; 래칫 시험 통과). 늘어난 키 없음. `index_script_tags` 는 HEAD 기준 이미 120(기준선 119는 기존 차이)이며 이 카드가 건드리지 않았다.
- **시험**: `test_r5_a4_claw_status_module_7216.py`·`test_r5_a4_claw_status_browser_7216.py` 갱신(deps 축소 + 옮긴 선언 마커 + 하니스 레지스트리 등록). 모듈 안으로 들어간 상태는 밖에서 못 보므로 행동 단정으로 전환(약화 아님): 불확실성은 공유 dispatch 키로 힌트 경로를 구동해 `clawCurrentDispatchIsUncertain()` 로, 카운트다운·타이머는 `clawRetryRemaining()`·틱 후 copy 로, 대기 단계는 localeKey·틱 렌더로 확인. 파급 정적 계약 3파일은 읽는 대상만 모듈로 전환(기준 유지): `test_b54_claw_execute_progress_ui`·`test_b54_claw_execute_retry_ui`·`test_b62_2299_claw_mvp_usability`. `test_r5_a5b_claw_form_module_7216.py` 는 자기 것이 없어 변경 없음. 로컬 관련 시험 62 passed.
- **뮤테이션 적발 확인**: (a) 옮긴 선언(`const clawUncertainKeys = new Set();`)을 app.js 에 되살리기 → 구조 계약 실패. (b) 모듈 `clawWaitStageKey` 폴백 변형(very-long→long) → vm 동작 시험 실패. 각 원복 후 재통과 확인.
- **초기 화면 장부**: `tools/r5_boot_ledger.py` 1440·390 — 1440 은 이동 전후 `body_structure_hash`·`listener_multiset_hash`(615건)·`window_names`(116)·`request_addresses_hash` 모두 동일. 390 은 같은 트리 재실행에서도 비결정적(리스너 멀티셋·body 해시·창 이름 변동; 이동 무관 환경 요인)이며 이동 전후 직접 비교는 1440 로 증명한다.
- **모듈 크기**: chat-claw-status-module.js 395 → 415줄(500 이하 유지).
- **동작·문구·DOM 변경 0**: 옮긴 본문은 deps 접두사 제거와 들여쓰기만 바뀌고 문자는 동일. create() 즉시 생성으로 DOM 조회 시점이 원래 선언 자리와 같다.
- **공유로 남긴 이름(목록만 — B6 몫)**: ClawStatus 공유 16개 — `input`·`shell`·`clawStatus`·`clawResultArea`·`clawExecuteButton`·`clawChannel`·`clawAction`·`clawSender`·`clawRetryBox`·`clawRetryButton`·`clawRetryHint`·`clawWorkspace`·`clawInFlight`·`clawLastDispatchKey`·`clawWaitStartedAt`·`conversationState`. 모듈 API 3개(`clawT`·`localeOr`·`selectedProductTier`)와 ClawForm 의 deps 24항목도 현상 유지(B7 몫).

### B2-3 진행 — ClawRun 자기 선언 이동 (2026-11-16)

- **대상**: ClawRun(자기 선언 8: 결과 화면 DOM `clawResultKind`·`clawApprovalActions`·`clawRequestEcho`·`clawRequestEchoText`·`clawArtifactMeta`·`clawArtifactName`·`clawArtifactSize`·`clawResultSuccessNote`; deps 자기 8). AndroidHandoff 는 대표 결정으로 보류.
- **방식**: 자기 선언을 모듈 `create()` 안으로(보강 1). 모듈은 원래 선언 자리에서 즉시 생성(`create({...})` — lazy 헬퍼 제거), `create()` 는 deps 를 읽지 않는다(#7832·#7844 와 같다). 자기 리스너 블록이 0개여서 `wire()` 이동은 없다(보강 2는 해당 없음). deps 에서 자기 것 8개 항목이 빠졌다 — 47→39항목(getter 45→37, setter 2 불변).
- **app.js**: 3,032 → 3,014(−18: 선언 8줄 이동 + 팩토리 축소 54줄 + 생성 블록 44줄). `appjs_deps_total` 516 → 508, `appjs_dom_lookups` 192 → 184. `appjs_forwarders` 174·`appjs_function_decls` 233·`appjs_listeners` 83 불변.
- **래칫 기준선**: `structure_baseline.json` 3키 실측 하향 — `appjs_lines` 3032 → 3014, `appjs_deps_total` 516 → 508, `appjs_dom_lookups` 192 → 184(감사 도구 실측; 래칫 시험 통과). 늘어난 키 없음. `index_script_tags` 는 HEAD 기준 이미 121(기준선 119는 기존 차이)이며 이 카드가 건드리지 않았다.
- **시험**: `test_r5_a5a_claw_run_module_7216.py`·`test_r5_a5a_claw_run_browser_7216.py` 갱신(deps 축소 + 옮긴 선언 마커 + vm 하니스 레지스트리 등록 + 브라우저 하니스 와이어링 추출 대상을 생성 블록으로). 옮긴 선언은 전부 DOM 참조라 밖의 엘리먼트 스텁과 모듈 조회가 같은 노드를 가리키며, 행동 단정은 그대로 유지했다(약화 없음). 파급 정적 계약은 깨진 것이 없어 변경 없음. 로컬 관련 시험 228 passed.
- **뮤테이션 적발 확인**: (a) 옮긴 선언(`const clawResultKind = document.getElementById("clawResultKind");`)을 app.js 에 되살리기 → 구조 계약 실패. (b) 모듈 `formatClawBytes` 단위 변형(B→bytes) → vm 동작 시험 실패. 각 원복 후 재통과 확인.
- **초기 화면 장부**: `tools/r5_boot_ledger.py` 1440 — 이동 전후 `body_structure_hash`·`listener_multiset_hash`(614건)·`window_names`(116)·`request_addresses_hash` 모두 동일. 390 은 환경 변동이라 참고만 한다.
- **모듈 크기**: chat-claw-run-module.js 437 → 448줄(500 이하 유지).
- **동작·문구·DOM 변경 0**: 옮긴 본문은 deps 접두사 제거와 들여쓰기만 바뀌고 문자는 동일. create() 즉시 생성으로 DOM 조회 시점이 원래 선언 자리와 같다.
- **공유로 남긴 이름(목록만 — B6 몫)**: ClawRun 공유 17개 — `input`·`app`·`authState`·`chatTransport`·`conversationState`·`PRODUCT_CLAW`·`clawApprovalEpoch`·`clawApprovalInFlight`·`clawExecuteButton`·`clawInFlight`·`clawLastDispatchKey`·`clawResultBadge`·`clawResultCard`·`clawResultDocx`·`clawResultEmpty`·`clawResultHint`·`clawResultPreview`. 그중 #7844 ClawStatus 공유 목록과 겹치는 5개: `input`·`clawExecuteButton`·`clawInFlight`·`clawLastDispatchKey`·`conversationState`. 모듈 API 21개도 현상 유지(B7 몫).

### B2-4 진행 — Nav 자기 선언 이동 (2026-11-17)

- **대상**: Nav(A10 모듈). 최신 main(`7dd775b6` 기준 카드 시작 `fd7f365e` 시점)에서 `tools/r5_appjs_map.py --modules` 로 다시 쟀다 — (가) 자기 선언 5개: `PANEL_ROUTE_HASH_BY_STATE`(779–784)·`OWNED_PANEL_HASHES`(785)·`PAGE_VIEWS`(795–806)·`PAGE_VIEW_BY_ID`(807–809)·`clawNavButton`(2461), (나) 자기 리스너 블록 **0개**(A10 이 이미 `wireNavRouteListener`·`wireNavEntryListeners` 로 옮겼고 app.js 는 원래 자리에서 wire 호출만 한다), (다) deps 자기 5 / 공유 20 / 모듈 API 6.
- **방식(보강 1)**: 자기 선언을 모듈 `create()` 안으로 옮겼다. 모듈은 원래 선언 자리(`PAGE_VIEWS` 가 있던 곳)에서 바로 만든다 — lazy `navModule()` 팩토리를 없애고 `const navModuleInstance = window.PadiemChatNavModule.create({…})` 로 즉시 생성하며, `create()` 는 deps 를 읽지 않는다(엄격 빈 deps 시험이 그대로 통과한다). Claw 진입 단추 조회도 모듈 안으로 들어갔고 조회 시점은 같은 부팅 구간이다.
- **조각 표**: `PANEL_ROUTE_HASH_BY_STATE` 는 `CALENDAR`·`LIBRARY`·`MEETING`·`ADVANCED_SETTINGS` 조각 상수에서 만들어지고 그 상수는 app.js 부팅 경로(`restoreShellFromHash` 계열, 2976–2995)가 계속 읽는다. 그래서 표는 모듈 안에서 **처음 쓸 때** deps 의 조각 상수로 만들어 `Object.freeze` 모양을 그대로 유지한다(생성 시점만 첫 사용으로 미뤘고 값·동작은 같다). app.js 에는 네 조각 상수만 남는다.
- **보강 2**: 옮길 자기 리스너 블록이 없어 app.js 는 기존 wire 호출 2줄(`navModuleInstance.wireNavRouteListener();`·`…EntryListeners();`)을 원래 블록 자리에 그대로 둔다(등록 시점·순서 보존). 전달 함수 7개는 `navModuleInstance.<이름>(...a)` 한 줄로 남는다(B7 몫).
- **app.js**: 3,014 → 2,978(−36). `appjs_deps_total` 508 → 507(Nav 33→32 항목: getter 30→29, setter 3 불변 — 자기 5개가 빠지고 공유 조각 상수 4개가 들어왔다), `appjs_dom_lookups` 184 → 183, `appjs_function_decls` 233 → 232(lazy 팩토리 제거). `appjs_forwarders` 174·`appjs_listeners` 83 불변.
- **래칫 기준선**: `structure_baseline.json` 4키 실측 하향 — `appjs_lines` 3014 → 2978, `appjs_deps_total` 508 → 507, `appjs_dom_lookups` 184 → 183, `appjs_function_decls` 233 → 232. 늘어난 키 0. `index_script_tags` 는 HEAD 기준 121(기준선 119는 기존 차이)이며 이 카드가 건드리지 않았다.
- **도구**: `tools/chat_structure_audit.py` 의 전달 함수 판정에 즉시 생성 인스턴스 형태(`모듈인스턴스.이름(...)`)를 추가했다. 이 보정이 없으면 B2 이후 전달 함수가 0으로 잘못 세어져 B7 완료 판정이 앞당겨진다. 같은 이유로 시험 도우미 `tests/_r5_function_source.py` 의 전달 함수 패턴도 두 형태를 모두 인식한다(이 보정으로 함수 본문을 모듈에서 찾는다).
- **시험**: `test_r5_a10_nav_module_7216.py` 갱신 — 즉시 생성·인스턴스 전달 함수·deps 표면(공유 조각 상수 4개 추가, 자기 5개 제거)·vm 엄격 deps 동작(빈 deps 로 `create()` 통과, 8함수·wire 2개 행동 단정 유지) + 옮긴 선언 마커 시험 추가. 파급 정적 계약은 읽는 대상만 모듈로 전환: `test_3531`·`test_4422`·`test_4647`(wire 호출·panelId)·`test_4765`·`test_calendar_ui`·`test_connectors_bright_calendar_state_ui`·`test_chat_screen_polish`·`test_b62_glass_home_chat_parity`. 로컬 관련 시험 **127 passed**.
- **뮤테이션 적발 확인**: (a) 옮긴 선언(`const clawNavButton = document.getElementById("clawNavButton");`)을 app.js 에 되살리기 → 구조 계약 실패. (b) 모듈 `pageViewFor` 폴백 변형(home→claw) → vm 동작 시험 실패. 각 원복 후 127 passed 재확인.
- **초기 화면 장부**: `tools/r5_boot_ledger.py` 로컬 실행이 **같은 트리 재실행에서도 비결정적**이다(after1 vs after3: 1440·390 모두 body 해시·리스너 순서 변동). 1440 한 실행에서 `PadiemClawDeviceDirectory` 창 이름 1개와 `document DOMContentLoaded` 리스너 1개가 더 잡혔는데, 이는 카드가 건드리지 않는 지연 로드 모듈의 경합이다. 이동 전 기록(before)과 390 은 창 이름 116개·리스너 614건·초기 요청 집합이 같고, 요청 주소 해시는 모든 실행에서 동일하다. 장부 동일성 증명은 CI 환경에서 한다.
- **동작·문구·DOM 변경 0**: 옮긴 페이지 계약 표는 문자 그대로, 조각 표는 같은 값·같은 동결 모양이다. 모듈 안 배치는 `deps.` 접두사가 사라지고 들여쓰기만 바뀌었다. AndroidHandoff 는 대표 결정대로 이 카드에서도 손대지 않았다.
- **공유로 남긴 이름(목록만 — B6 몫)**: Nav 24개 — `AUTOMATION_ROUTE_HASH`·`CLAW_ROUTE_HASH`·`CONNECTORS_ROUTE_HASH`·`CALENDAR_ROUTE_HASH`·`LIBRARY_ROUTE_HASH`·`MEETING_ROUTE_HASH`·`ADVANCED_SETTINGS_ROUTE_HASH`·`PRODUCT_CHAT`·`PRODUCT_CLAW`·`app`·`authState`·`automationDestinationReady`·`clawArtifactShownFor`·`clawManualForm`·`clawResultArea`·`clawWorkspace`·`conversationArtifactContext`·`conversationProduct`·`conversationState`·`emptyState`·`input`·`messageList`·`pendingClawRunFocusId`·`shell`. 앞 카드들과 겹치는 이름은 `input`·`shell`·`app`·`authState`·`conversationState`·`conversationProduct`·`PRODUCT_CLAW`·`clawResultArea`·`clawWorkspace`·`clawManualForm`·`clawArtifactShownFor` 등이다.

### B2 완료 요약 (카드 1~4, 2026-11-17)

| 카드 | PR | app.js 줄 수 | deps 총계 |
|---|---|---:|---:|
| B2-1 PcRun + Connectors | #7832 | 3,113 → 3,059 | 546 → 530 |
| B2-2 ClawStatus (+ClawForm 동행) | #7844 | 3,063 → 3,032 | 530 → 516 |
| B2-3 ClawRun | #7850 | 3,032 → 3,014 | 516 → 508 |
| B2-4 Nav | #7869 | 3,014 → 2,978 | 508 → 507 |

- **합계**: app.js 3,119(B2-0 기준) → 2,978(−141줄). `appjs_deps_total` 546 → 507(−39). `appjs_forwarders` 174·`appjs_listeners` 83 은 카드 내내 불변 — B2 는 선언·리스너만 옮기고 등록부(B7)를 만들지 않는다.
- **뮤테이션**: 카드마다 2건(되살리기·동작 변형) 적발 확인 후 원복.
- **보류**: AndroidHandoff 는 대표 결정으로 T2(B2·B6·B7)에서 옮기지 않는다 — 안드로이드 작업 때 처리한다.
- **B6 로 넘긴 공유 이름 전체(중복 제거 48개)**: `MESSAGE_LIFECYCLE`, `input`, `shell`, `app`, `authState`, `conversationProduct`, `conversationState`, `PRODUCT_CHAT`, `PRODUCT_CLAW`, `connectorsError`, `googleCalendarReadActivationAfterConnectReturn`, `googleConnectorConnectInFlight`, `clawAction`, `clawApprovalEpoch`, `clawApprovalInFlight`, `clawArtifactShownFor`, `clawChannel`, `clawExecuteButton`, `clawInFlight`, `clawLastDispatchKey`, `clawManualForm`, `clawResultArea`, `clawResultBadge`, `clawResultCard`, `clawResultDocx`, `clawResultEmpty`, `clawResultHint`, `clawResultPreview`, `clawRetryBox`, `clawRetryButton`, `clawRetryHint`, `clawSender`, `clawStatus`, `clawWaitStartedAt`, `clawWorkspace`, `chatTransport`, `emptyState`, `messageList`, `pendingClawRunFocusId`, `automationDestinationReady`, `conversationArtifactContext`, `AUTOMATION_ROUTE_HASH`, `CLAW_ROUTE_HASH`, `CONNECTORS_ROUTE_HASH`, `CALENDAR_ROUTE_HASH`, `LIBRARY_ROUTE_HASH`, `MEETING_ROUTE_HASH`, `ADVANCED_SETTINGS_ROUTE_HASH`.
- **다음**: B3(최근 대화·실행 기록) → B5(설정·사이드바·대화·달력) → B4(로그인·계정) → B6(공유 문맥) → B7(등록부).

### B3 진행 (2026-11-17)

| 항목 | 전 | 후 |
|---|---:|---:|
| app.js | 2,978 | 2,933 |
| `appjs_deps_total` | 507 | 480 |
| `appjs_dom_lookups` | 183 | 175 |
| `appjs_listeners` | 83 | 81 |
| `chat-history-module.js` | 542 | 444 |
| `chat-run-history-module.js` | 309 | 447 |

- **history 모듈 자기 선언**: `historyReadSequence`·`HISTORY_TITLE_MAX_CHARS` 를 `create()` 로 옮겼다(create()는 deps 를 읽지 않는다). 최근 대화 메뉴 리스너 2개(document click·keydown)는 `wireMenuListeners()` 로 옮기고 app.js 가 원래 블록 자리에서 부른다. R-11 확인: 장부의 document click·keydown 15쌍이 이동 전후 같은 상대 순서다.
- **모듈 사이 이동**: 실행 목록 함수 6개(`clearClawRunHistoryPdfPreviews`·`setClawRunHistoryStatus`·`clawRunHistoryErrorMessage`·`fetchClawRunHistory`·`loadClawRunHistory`·`syncClawRunHistoryVisibility`)와 패널 DOM·상태 7개(`clawRunHistoryDisclosure`·`Loading`·`Error`·`List`·`Empty`·`LeftSurface`·`VisibilityEpoch`)를 `chat-run-history-module.js` 로 옮겼다.
- **공유 목록**: B6 48개 목록에는 `clawRunHistory*` 이름이 없어 목록은 그대로다. 공유 컨텍스트 접근자 3개(`setClawRunHistoryStatus`·`loadClawRunHistory`·`syncClawRunHistoryVisibility`)는 지우고 run-history 모듈 API 등록으로 대체했고, history 모듈 deps 에서 `clawRunHistory*` 항목 13개가 사라졌다.
- **시험**: 두 r5 계약 시험을 새 구조로 갱신하고(전달 함수 대상 `runHistory`, 패널 소유 선언, `wireMenuListeners()` 호출), 3932·b54·7297·execute-progress·plain-korean 의 위치 단정만 새 위치로 옮겼다. 행동 단정은 그대로다.
- **뮤테이션**: (a) 옮긴 패널 선언을 app.js 에 되살리기 → 구조 계약 실패. (b) `fetchClawRunHistory` 의 일반 실행 필터 제거 → 7297 실행 기록 필터 시험 실패. 각 원복 후 관련 287 passed.

### B5 진행 — 설정·사이드바·대화·달력 자기 선언 이동 (2026-11-17)

| 항목 | 전 | 후 |
|---|---:|---:|
| app.js | 2,933 | 2,870 |
| `appjs_deps_total` | 480 | 459 |
| `appjs_dom_lookups` | 175 | 161 |
| `appjs_listeners` | 81 | 69 |
| `chat-settings-module.js` | 69 | 114 |
| `chat-sidebar-module.js` | 77 | 94 |
| `chat-conversation-module.js` | 474 | 482 |
| `chat-calendar-module.js` | 245 | 251 |

- **설정**: `advancedSettingsReturnState`·`settingsCloseButton`·`settingsAdvancedOpen`·`advancedSettingsBack`·`advancedMenuButtons`·`advancedPageBlocks` 를 `create()` 로 옮겼다. 리스너는 `wireTierChange()`·`wireAdvancedSettings()`·`wireSettingsDialog()` 로 나눠 app.js 가 원래 자리에서 부른다(순서 보존).
- **사이드바**: `mobileMenu`·`mobileClose`·`sidebarCollapseButton`·`sidebarRestoreButton`·`sidebarScrim` 를 `create()` 로, 클릭 리스너 5개를 `wire()` 로 옮겼다.
- **대화**: `attachmentTray`·`attachmentChipList`·`attachmentKeyCounter`·`composerInlineHint`·`composerInlineHintTimer` 만 이동. `newChatButton`·`composerForm`·`cancelStreamButton` 은 app.js 리스너가 직접 읽어 공유로 남겼다(B6 몫).
- **달력**: `GOOGLE_CALENDAR_CONNECTOR`·`GOOGLE_CALENDAR_TICKET_ENDPOINT`·`GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT` 상수만 `create()` 로 옮겼다. `googleCalendarReadState` 는 app.js 소유(세션 내 grant 진실)와 deps getter/setter 경로를 그대로 유지한다.
- **스트리밍**: 모듈 전용 선언이 없어 이동 없음(리스너 1개만 있고 `cancelStreamButton` 은 공유).
- **시험**: 두 r5 계약 시험의 하네스가 모듈 소유 DOM 을 만들도록 바꾸고(create() 조회와 같은 노드), `wire*()` 를 모듈 표면 목록에 추가했다. deps getter 계약은 모듈 소유 상태의 행동 단정으로 바꿨다. 파급 정적 계약(7297·b62)은 읽는 대상만 새 위치로 옮겼다.
- **장부(1440)**: 화면 구조 해시·리스너 멀티셋·창 이름·초기 요청 동일. document click·keydown 15쌍의 상대 순서 동일(절대 index 는 DOMContentLoaded 비결정으로 1칸 이동, after 반복 실행도 서로 다름).
- **뮤테이션**: (a) 옮긴 설정 리스너를 app.js 에 되살리기 → 래칫 실패(appjs_lines +2, dom +1, listeners +1). (b) `mobileClose.focus()` → `mobileMenu.focus()` → 휴대폰 오버레이 포커스 시험 실패. 각 원복 후 통과.

### B4-1 진행 — 계정 함수 `chat-account-module.js` 분리 (2026-11-17)

- **대상**: `chat-auth-module.js`의 재설정 9함수·변경 3함수·삭제 7함수와 삭제 공통 `syncDeleteButton`을 계정 모듈로 이동했다. 재설정은 `passwordResetTokenFromLocation`·`clearPasswordResetFragment`·`showPasswordResetView`·`hidePasswordResetViews`·`openPasswordResetRequest`·`openPasswordResetConfirm`·`closePasswordResetViews`·`submitPasswordResetRequest`·`submitPasswordResetConfirm` 다. 변경은 `openPasswordChangeDialog`·`closePasswordChangeDialog`·`submitPasswordChange`, 삭제는 `resetAccountDeleteConfirm`·`resetAccountSharedDeleteConfirm`·`openAccountDeleteConfirm`·`openAccountSharedDeleteConfirm`·`syncAccountDeleteButton`·`syncAccountSharedDeleteButton`·`submitAccountDelete` 다. app.js는 기존 호출 호환을 위해 19개 한 줄 전달 함수를 `accountModule()`로 연결하고 `syncDeleteButton`은 모듈 안에서만 부른다.
- **자기 DOM 25개**: 삭제 관련 9개(`accountDeleteOpen`·`accountSharedDeleteOpen`·두 확인 이메일 입력·두 삭제 버튼·두 오류·`accountSharedDeleteConfirm`), 변경 관련 9개(`passwordChangeOpen`·`Dialog`·`DialogClose`·`Form`·`Current`·`New`·`Confirm`·`Error`·`Submit`), 재설정 관련 7개(`passwordResetRequestForm`·`RequestSubmit`·`ConfirmForm`·`Confirm`·`ConfirmSubmit`·`Back`·`ConfirmBack`)를 `create()`에서 조회한다. 로드 시 조회는 없다.
- **리스너 15개**: 재설정 열기 click·요청/확인 submit·뒤로 가기 2click, 변경 열기/닫기 click·form submit·dialog cancel, 단일/공통 삭제 열기 click·확인 이메일 input 2개·삭제 실행 click 2개를 `wire()`가 원래 app.js 블록 자리 호출로 같은 순서 등록한다. 이전 WIP 보고의 13개는 재확인 결과 실제 등록 수와 달라 15개로 정정했다.
- **공유 DOM은 deps로 유지(B6 몫)**: `accountDeleteConfirm`, `authDialog`, `passwordLoginContinue`, `passwordLoginError`, `passwordResetOpen`, `passwordResetPanel`, `passwordResetEmail`, `passwordResetNew`, `passwordResetRequestView`, `passwordResetRequestError`, `passwordResetRequestStatus`, `passwordResetConfirmView`, `passwordResetConfirmError`, `passwordResetConfirmStatus`다. 특히 `passwordLoginContinue`는 계정 모듈이 직접 조회하지 않고 `deps.passwordLoginContinue`로 받으며, app.js getter는 auth 모듈의 `emailContinueElement()`를 그대로 사용한다. 공유 하네스 DOM 레지스트리에는 새 이름을 추가하지 않았다.
- **로그인 상태는 소유 이전 없음**: app.js의 `authDialogView`는 `showPasswordResetView`·`hidePasswordResetViews`가 request/confirm/login으로 쓰고, app.js의 `passwordResetToken`은 `openPasswordResetConfirm`에서 설정하며 hide/close/confirm 성공에서 비운다. 각각 기존 deps getter+setter 경로만 쓴다. `authState`는 읽기만 한다. 계정 모듈로 소유를 옮긴 로그인 화면 단계·입력값·진행 플래그는 없다.
- **계정 deps**: 27 getter + 2 setter(`authDialogView`, `passwordResetToken`). 계정·auth 두 모듈 API 사이 호출은 기존 app.js 전달 함수와 deps 경로를 유지한다. `emailContinueElement`는 auth 모듈 반환 API로 추가해 공유 요소 조회를 한 곳에 고정했다. `accountModule` 팩토리는 화살표 함수로 만들어 app.js 함수 선언 수가 늘지 않게 했다.
- **수치**: app.js 2,878 → **2,811**줄, `appjs_deps_total` 461 → **451**, `appjs_dom_lookups` 161 → **136**, `appjs_listeners` 69 → **54**, `appjs_forwarders` 174 불변, `appjs_function_decls` 232 불변. auth 모듈 794 → **499**줄, 계정 모듈 **387**줄. `APP_JS_CAP` 3,216 → **2,911**(실측+100), `structure_baseline.json`도 같은 실측으로 내렸다. `index_script_tags` 121 → 122(새 모듈 1개, 래칫 제외 항목).
- **골든**: `test_r5_step4_auth_module_7216.py::test_b4_account_golden_paths_preserve_requests_and_screen_copy`(`_r5_b4_account_golden.py` helper)가 재설정 요청·변경 성공/실패·삭제 미확인/확정 5경로의 요청 주소·메서드·본문 키·화면 문구를 합성 응답으로 고정한다. 이동 전 main `1af36230`과 이동 후 결과 JSON이 byte-identical 했다(경로 5, SHA-256 `0a3f5d8d5317099435c95d10d43ca0d038031a3af2e2029d260fe9cd12a64501`). 운영 로그인·계정은 사용하지 않았다.
- **장부(1440)**: 반복 실행의 기존 `PadiemClawDeviceDirectory`/`document DOMContentLoaded` 경합은 같은 트리 재실행 대조로 확인했다. 대조 실행에서 구조 해시 `906933a36c9195b8dc3d784063ee7fd6d61aeff7ecf95b810cc004903494e938`, 리스너 멀티셋 해시 `26f345104d94a382c0cdf8b3a919fef91799ffd3082ee357c968a8907a3ff557`(614건), 초기 요청 집합이 전후 동일했다. 창 이름은 새 팩토리 `PadiemChatAccountModule` 1개 외 변동 없고, document click 6·keydown 9의 상대 순서도 동일하다.
- **시험 읽기 대상만 이동**: step4 auth module/browser 계약은 두 모듈을 모두 생성해 기존 기대값을 유지하고, 4416·5479·7647·5434·5481·b62_3084·account_deletion도 기대값 변경 없이 읽는 파일만 계정 모듈로 옮겼다(5481은 auth+account 합성). 새 골든만 B4-1 증거로 추가했다. 뮤테이션: (a) `syncDeleteButton`의 확인 조건을 `button.disabled = false`로 바꾸면 미확인 `POST /api/account/delete`를 골든이 적발, (b) 옮긴 `passwordResetOpen` 리스너를 app.js에 되살리면 래칫이 `appjs_lines` +1·`appjs_listeners` +1로 적발했다. 각 원복 후 골든·래칫 통과.

### B4-2 계획 — 로그인 흐름 잔여분 (2026-11-17, 코드 수정 전 확정)

기준: `origin/main` `7628d3c5f`(B4-1 병합 `b421195a1` 포함). 근거 출력: `tools/r5_appjs_map.py`(`b42-map.json`)·`--modules`(`b42-modules.json`).

**남은 항목 표** (로그인 세션 구역: 최상위 함수 40개 129줄 · 변수 54개 96줄 · 모듈 자체 선언 13개 20줄 · 자체 리스너 5블록 12줄):

| 흐름 | app.js 잔여 항목 | 분류 |
| --- | --- | --- |
| 세션 상태 확인·갱신 | `SESSION_PRESENTATION`(1502–1509, 8줄), `AUTH_SERVER_UNREACHABLE`(1669), `AUTH_UNREACHABLE_RETRY_DELAY_MS`(1674), `CUSTOM_AUTH_FAILURE_CODE`(835), `document visibilitychange`(1779–1781), `padiem:auth-state`(2806), `loginButton` click(2165–2185), 상태 getter/setter 9개 | 상수·리스너 **옮김**, `authState`·`authViewEpoch`·`authDialogView`·`passwordResetToken`·`pendingNotification*` getter/setter **app.js 유지(B6 몫)** |
| 로그인 대화상자 열기·닫기·전환 | `authDialogClose`(466), `authDivider`(476), 대화상자 함수 9개(`setAuthFormError`·`emailContinueElement`·`syncAuthDialogMethods`·`openAuthDialog`·`closeAuthDialog`·`authServerUnreachableError`·`passwordAuthAnswer`·`passwordAuthRequest`·`setAuthStatusMessage`), `authDialogClose` click(2202), `authDialog` cancel(2204–2208), `googleLoginButton` click(2210–2218), `guestLoginEntryButton`(2163)·click(2164) | **옮김 → `chat-login-dialog-module.js`(신설)** |
| 이메일·Google 로그인 시작 | 위 `loginButton`·`googleLoginButton`·`guestLoginEntryButton` 리스너, `passwordAuthRequest`(이미 auth 모듈) | 리스너 **옮김**, 요청 함수는 대화상자 모듈로 이동 |
| 가입 | `passwordRegister*`·`age_confirm` 관련 함수는 B4-1에서 계정 모듈로 이전 완료, app.js에는 한 줄 전달 함수만 | **이번 변경 없음**(전달 함수는 B7 몫) |
| 로그아웃 | `settingsLogoutButton` click(2187–2200), `signOutCurrentAccount`(이미 auth 모듈) | 리스너 **옮김**, 함수는 auth 모듈 유지 |
| 프로필 단추·패널 생성 | 생성 블록(524–537), `accountAvatar`(506), `profileToggle`·`profileSettingsAction` click(2230–2234), `document pointerdown`(2235–2237), `keydown` Escape 중 프로필 패널 부분(2254–2260), `closeProfilePanel` | 생성 블록·리스너 **옮김**(`keydown` 블록은 사이드바 부분과 합치지 않고 원래 자리에서 분리 호출) |
| 나이 확인 안내(#7853) | 클라이언트 전용 코드 없음(서버가 확인 화면 서빙). 세션 확인 성공/401 경로로만 표현 | **해당 없음**, 세션 확인 경로에서 검증 |
| 공용 로그인 대기 문구(#7647) | `loginPending`(auth 모듈 148–149), 계정 모듈 273 재시도 항목 | **이번 변경 없음**, 골든에서 문구 유지 확인 |
| 모듈 연결부 | `authModule`(146–235, 90줄), `accountModule`(242–272, 36줄), 한 줄 전달 함수 174개 | **app.js 유지(B7 몫)**. 초기화 호출·저장소 접근도 §2.2대로 유지 |

**파일 나눔 결정**: 옮길 줄은 자체 선언 20 + 생성 블록 14 + 리스너约70 + 대화상자 함수 160 + 모듈 머리말约30 = **约294줄**로 450줄 미만 → B4-2a/b 분할 없이 한 PR. 반면 현 `chat-auth-module.js` 499줄에 잔여 session 리스너·선언约135줄을 더하면 **约634줄로 600줄 초과** → 설계 §2.1의 "셋째 파일" 안을 택해 `chat-login-dialog-module.js`(대화상자 함수+대화상자 DOM+대화상자 리스너, 约330줄)로 분리하고, `chat-auth-module.js`는 세션 상태·로그인·로그아웃 约400줄로 유지한다. B6 몫 공유 DOM 14개(`accountDeleteConfirm`·`authDialog`·`passwordLoginContinue`·`passwordLoginError`·`passwordResetOpen`·`passwordResetPanel`·`passwordResetEmail`·`passwordResetNew`·`passwordResetRequestView`·`passwordResetRequestError`·`passwordResetRequestStatus`·`passwordResetConfirmView`·`passwordResetConfirmError`·`passwordResetConfirmStatus`)는 새 하네스 레지스트리에 추가하지 않고 deps로만 받는다. UI 계약 모듈 수 현재 401 / 상한 450 → 새 계약 시험 2개 추가 후 403으로 상한 내.


### B4-2 결과 — 로그인 흐름 모듈 분리 (2026-11-17)

- **대상**: `origin/main` `7628d3c5f` → rebase 후 `043a31450`. 브랜치 `refactor/7812-t2-b4-2`. 워드마크·문구·요청 주소·대화상자 흐름·오류 순서 변경 0.
- **옮긴 것**: 대화상자 함수 9개(`setAuthFormError`·`emailContinueElement`·`syncAuthDialogMethods`·`openAuthDialog`·`closeAuthDialog`·`authServerUnreachableError`·`passwordAuthAnswer`·`passwordAuthRequest`·`setAuthStatusMessage`)를 `chat-auth-module.js` → 신규 `chat-login-dialog-module.js`(**227줄**). app.js의 자체 선언 13개(20줄), 프로필 패널 생성 블록(14줄), 리스너 10개를 두 모듈의 `create()`·`wire*()`로 이전. `auth 모듈 499 → 425줄`.
- **app.js 유지**: `authState`·`authViewEpoch`·`authDialogView`·`passwordResetToken`·`pendingNotification*` 등 공유 상태 getter/setter, 모듈 연결부, 한 줄 전달 함수 174개, 초기화 호출, 저장소 접근. 초기화 순서(`PadiemChatSession.bind` 등)는 그대로다.
- **B6 몫 공유 DOM 14개**: B4-1의 14개 이름을 하네스 레지스트리에 추가하지 않고 deps로만 전달. 대화상자 모듈의 자기 DOM은 `authDialogClose`·`authDivider`·`guestLoginEntryButton`·`accountProfilePanel` 4개.
- **호출 순서**: `wire*()`를 원래 리스너 블록 자리에서 호출해 document click·keydown 상대 순서를 보존했다. 분리 불가능한 프로필 Escape 분기는 app.js에 남기고 새 모듈의 `profilePanelElement()`를 읽는다.
- **수치**: app.js 2,811 → **2,731**줄, `appjs_deps_total` 451 → **449**, `appjs_dom_lookups` 136 → **133**, `appjs_listeners` 54 → **44**, `appjs_forwarders` 174·`appjs_function_decls` 232 불변, `index_script_tags` 122 → 123. `APP_JS_CAP` 2,911 → **2,831**(실측+100), `structure_baseline.json`도 실측으로 하향. rebase 충돌은 감사 도구 실측으로 덮어썼다.
- **창 이름**: main과 같은 방법으로 3회씩 측정. `__padiemClawRunHistoryIncludeGeneral`은 양쪽 3회 모두 관측된 측정 시점 노이즈였다. 증가분은 새 팩토리 `PadiemChatLoginDialogModule` **1개뿐**, 감소 0.
- **장부(1440·390, 3회 재측정)**: 구조 해시 `ea5c5290d6015d70ab218f28bceb948b1cbb0a8c9c60177a72385ae105bc0366`, 리스너 멀티셋 `9f19c65f772e28121c3122c242ca60fff41a7dc795b541dc3c5f02964072598c`, 초기 요청 `0ee76abdcf29d74d99caa725567ae0b6a303ab4765b92372f4fb4d0d984f321d` — main과 전부 동일. 리스너 615건.
- **골든**: `test_r5_b4_2_login_flow_golden_7216.py` + `_r5_b4_2_login_golden.py`. 같은 하네스를 clean main(`043a31450`)과 이 브랜치에 적용해 로그인 성공·실패, 로그아웃, 세션 만료, 대화상자 열고 닫기 5경로의 요청·문구를 비교 — byte-identical. 스냅샷 `fixtures/r5_b4_2_login_golden.json` SHA-256 `080188e4277bc8bf…`. 운영 계정 미사용.
- **시험**: 신규 계약 2종(vm 하네스 · Chromium) 통과, UI 계약 모듈 401 → **402/450**. 기존 시험은 읽는 범위를 `app.js + 새 모듈 본문`으로 넓히고 `app.js가 wire*()를 호출한다` 단언을 추가했다(대상 교체·축소·제거 없음). clean main 기준 기존 실패: `5115` 1건, `7065` 2건, `7543` 2건, `r5_a3` 1건, `r5_a9` 1건 — this PR에서 건드리지 않음.
- **뮤테이션**: (a) 옮긴 리스너를 app.js에 되살리면 래칫이 `appjs_listeners` +1로 적발, (b) 로그아웃 요청 1개를 빼면 골든이 적발. 각 원복 후 통과.


### B6 계획 — 공유 문맥 가: 공유 상태·단일 객체 (2026-11-17, 코드 수정 전 확정)

**선택 이유**: B5는 이미 이 지도의 "B5 진행" 절(2026-11-17)에서 완료됐고 design §3.5는 B6의 선행을 B2~B5로 정한다. B7(등록부)은 B6 뒤에 온다. 따라서 다음 묶음은 B6이다.

**근거 자료**: design §1.7(바뀌는 공유 상태 24개 + 읽기 전용 단일 객체·상수 54개 = 78개, 선언 147줄), §2.3(전역 상태를 모을 곳), §3.5 B6. 현 `chat-app-context.js`는 42줄로 이미 `Object.create(shared)` 기반 단일 이름 공간과 등록부를 갖고 있으며, app.js가 `authState`·`shell`·`uiT` 등 22개를 live accessor로 넘기는 중이다.

| 분류 | 항목 |
| --- | --- |
| 옮김 | 각 모듈 연결부에서 중복된 공유 getter·setter를 지우고 `Object.setPrototypeOf(자기 getter 목록, app)`으로 공유 문맥을 물려받는다. 현재 app.js의 18개 연결부에 걸친 중복 공유 이름은 104개( B4-2로 늘어난 대화상자 이름 포함). 공유 문맥 쪽에는 이 이름들의 live accessor를 모은다. **소유 이전은 하지 않는다** — 설계 §3.5 B6의 선언 이전 안은 "공유 상태 소유는 app.js" 원칙과 충돌하므로 이번 묶음에서는 접근자 통합만 수행. |
| app.js 유지 | 모듈 생성과 `wire*()` 호출, 한 줄 전달 함수 174개, 초기화 순서(`PadiemChatSession.bind` 등), 보안 감사가 파일을 고정한 저장소 접근(`readStoredAndroidHandoff`·`storeAndroidHandoff`·`resumeAndroidHandoff`). 공유 상태의 **소유权**을 옮기는 것이 아니라 접근 경로를 문맥으로 모으는 것이므로 초기값·대입 의미는 그대로다. |
| 공유 | 78개 이름은 문맥 접근자로만 노출. 하네스 DOM 레지스트리에 새 이름을 추가하지 않는다. 같은 이름이 두 번 등록되면 기존 등록부가 예외를 낸다. |

**원칙 확인**: 상태 소유는 app.js 유지( B4와 동일), 공유 DOM은 deps로만, 하네스 레지스트리에 이름 추가 없음, 한 줄 전달 함수 유지.
**위험·확인**: `activeProject`(읽기 6·쓰기 5), `authState`(읽기 16), `authViewEpoch`, `clawApprovalEpoch`, `inFlight`의 읽기·쓰기가 모든 경로에서 같은 값을 보는지. 원래 app.js 클로저 변수와 문맥 접근자의 초기값 및 대입 시점이 동일한지. B5에서 상태 소유를 모듈로 옮겼다 되돌린 전례가 있으므로 소유 이전 없이 접근자만 통합한다.

**증거 계획**: 부팅 장부 1440·390 3회(구조·리스너·창 이름·초기 요청), 골든(clean main에서 생성한 로그인 흐름 5경로 + 공유 상태 경로), 뮤테이션 2건, 루트 e2e 3098·5573, 구조 래칫 실측 하향.


### B6 결과 — 공유 문맥 접근자 통합 (2026-11-17)

- **선택/원칙**: B5는 이미 완료(지도 "B5 진행" 절)라 B6. 소유 이전은 하지 않고 "공유 상태 소유는 app.js" 원칙을 유지. 공유 DOM은 deps로만, 하네스 레지스트리 이름 추가 0, 한 줄 전달 함수 174개 유지.
- **구현**: 18개 모듈 연결부 중 2개 이상이 갖던 공유 getter·setter 103개를 각 연결부에서 제거하고 `create(Object.setPrototypeOf({자기 것}, app))`로 공유 문맥을 상속. `chat-app-context.js`에 87개 live accessor 추가(쓰기 가능 20개는 getter+setter), 등록부는 모듈 API가 기존 accessor를 덮어쓰되 같은 이름을 두 모듈이 제공하면 계속 예외.
- **수치**: app.js 2,811 → **2,582**줄, `appjs_deps_total` 451 → **161**, `appjs_dom_lookups` 136 → 133, `appjs_listeners` 54 → 44, `index_script_tags` 123 불변. `APP_JS_CAP` 2,831 → **2,682**(실측+100), `structure_baseline.json` 실측 하향.
- **장부(1440·390, 3회)**: 구조 해시 `ea5c5290d6…`, 리스너 멀티셋 `9f19c65f77…`, 초기 요청 `0ee76abdcf…` — clean main과 동일. 창 이름 증가는 B4-2의 `PadiemChatLoginDialogModule` 1개뿐, B6으로 인한 변동 0.
- **시험**: R5 계약 시험의 `create({` 리터럴을 `create(`로 넓히고(_r5_b6_wiring.create_block으로 두 형태 모두 파싱), deps 표면 단언을 "자기 것 ∪ 문맥 상속"으로 넓힘. VM 하네스에 `app` 스텁 주입. 기대값·동작 단언 축소 없음. 골든 5경로(main 생성 스냅샷) 유지, 전체 관련 시험 2,076건 통과. clean main에서 재현되는 기존 실패는 `7065` 2건뿐.
- **뮤테이션**: (a) 옮긴 공유 getter를 모듈 연결부에 되살리면 래칫이 deps +1로 적발, (b) 문맥의 `authState` accessor를 오값으로 바꾸면 부팅 장부의 구조·초기 요청이 달라져 적발. 각 원복 후 통과.

### B6 리뷰 반영 — 시험 정확도 복원 + 문맥 이름 충돌 가드 (2026-11-18)

- **시험 정확도 복원(넓히기만)**: 모듈 시험 8건·스트리밍 2건의 deps 단언을 `gets ⊆ EXPECTED` 그리고 `gets ∪ (EXPECTED ∩ context_names) == EXPECTED`(setter 동일)로 복원. 스트리밍은 main 의 43개 getter 이름을 `EXPECTED_GETTERS`로 명시해 개수 비교(len ≤ 43)를 삭제. `_r5_b6_wiring.create_receives_app_context`를 추가해 create 가 실제 공유 문맥을 deps prototype(`}, app))`)으로 받는지도 단언 — 문맥 어딘가에 이름이 있는 것만으로 통과하지 않는다. `create(` 로 넓혔던 리터럴 단언은 `create(Object.setPrototypeOf({` 로 원형 복원(test_5015·5573·step3·step4 포함).
- **중복 이름 실측**: provide() API ∩ 문맥 접근자 = **1개**(`runHistory.syncClawRunHistoryVisibility`), deps 리터럴 get/set ∩ 문맥 접근자 = **0개**, 문맥 소유 참조(공유 DOM 5개·provide) ∩ 모듈 API = **0개**.
- **충돌 가드**: `chat-app-context.js`에 `ACCESSOR_SHADOW_ALLOWLIST` 도입. 목록 안 1개 이름의 근거 — runHistory 가 실제 소유자: app.js 접근자와 한 줄 전달 함수가 최종 위임하는 대상이 `runHistory.syncClawRunHistoryVisibility`이고 모듈 구현은 `this`를 읽지 않아 어느 경로든 같은 동작. 목록 밖 접근자 겹침과 문맥 소유 참조 겹침은 오류. 기존 모듈 중복 등록·중복 이름 오류 유지. 새 시험 `test_r5_b6_context_name_guard_7216.py`.
- **증거(재측정)**: 부팅 장부 1440·390 3회 — 리스너 멀티셋·초기 요청 주소는 branch=main 3/3 일치. 구조 해시는 같은 트리 안에서도 두 변형(`ea5c5290…`/`906933a3…`)이 번갈아 관측되는 부팅 시점 비동기 렌더 경합(MCP 게이트웨이 클라이언트 행 빈/로그인 + 컴포저 PC 칩 액션 span 렌더 시점)이며 변형 집합이 main·branch 동일 — 브랜치가 새 변형을 만들지 않았다. 골든 5경로 스냅샷 통과, 뮤테이션 2건 검출((a) 문맥 accessor 제거 → 복원된 정확 비교 3건 적발, (b) allowlist 면제 제거 → 이름 가드 시험 적발; 각 원복 후 통과).

### B7 계획 — 모듈 등록부, PR 단위 분해 (2026-11-18, 코드 수정 전 확정)

- **app.js 분류(2,582줄 기준)**:
  - (가) 모듈 생성·`wire()`·초기화 순서(라우트 복원, 세션 bind, 창 계약) — **남긴다**(B7 최종 형태의 본체). sessionStorage 보안 감사 3함수도 R-06에 따라 남긴다.
  - (나) 모듈 연결부(팩토리 함수 + deps 리터럴) — 1차 PR 은 전달 함수만 등록부 경유로 전환하고 연결부는 유지한다. 연결부 소멸은 후속 PR.
  - (다) 한 줄 전달 함수 **174개**(감사 도구 기준, 17개 대상): conversationModule 19 · accountModule 19 · clawStatusModule 19 · clawRunModule 15 · coreModule 14 · authModule 12 · historyModule 12 · androidHandoffModule 9(보류 — 지도 B3 기록대로 안드로이드 작업 때 처리) · calendarModule 8 · loginDialogModule 8 · navModuleInstance 7 · pcRunModule 7 · runHistory 6 · streamingModule 5 · settingsModule 5 · connectorsModule 5 · sidebarModule 4.
  - (라) 그 밖: 창 계약 4종(`PadiemChatRouting`·`PadiemAppSwitch`·`PadiemChatSession.bind`·`PadiemClawSession.bind`)·해시 복원·locale/attachment 상수.
- **등록부 설계**: 새 추상화를 만들지 않는다 — B6 문맥의 `app.provide(이름, 인스턴스)` 가 곧 등록부다(automation·automationForm·memory·runHistory·localPcPanel 은 이미 등록됨). 전달 함수 삭제 후 호출자 3종 전환: (1) app.js 내부 호출자는 등록된 조각 직접 호출(`runHistory.foo(...)` — provide 위치가 원래 팩토리 생성 위치라 실행 순서 불변), (2) 다른 모듈 deps 리터럴 getter 는 등록부 값을 반환(`get loadClawRunHistory() { return runHistory.loadClawRunHistory; }` — getter 를 지우지 않아 deps 표면 시험 불변), (3) 문맥 접근자도 같은 방식. 대상 메서드는 전부 클로저형(`this` 미사용)이라 수신자 변화가 없다. 하네스에 새 이름 등록 없음.
- **PR 단위표(각 반나절 이하)**: 1차 runHistory 6(기존 등록) → 2차 sidebar 4(신규 provide "sidebar") → 3차 settings 5 → 4차 streaming 5 → 5차 connectors 5 → 6차 nav 7 → 7차 pcRun 7 → 8차 calendar 8 → 9차 loginDialog 8 → 10차 history 12 → 11차 auth 12 → 12차 core 14 → 13차 clawRun 15 → 14차 clawStatus 11(재시도·복구·대기 — 19개를 상한 15에 맞춰 기능 덩어리로 분할, 잔여 8개는 후속 차) → 15차 account 19(같은 방식으로 분할) → 16차 conversation 19. androidHandoff 9는 보류. nav 이후 묶음은 조각 API 가 공유 접근자(setNavActive·closeSidebar 등)와 겹치므로, 그때마다 접근자를 등록부 값으로 재지시하거나 allowlist 근거를 매긴다(B6 가드 규칙 유지).
- **1차 PR 범위**: runHistory 6개 — 모듈이 이미 `app.provide("runHistory", …)` 로 등록되어 있어 등록부 경로가 존재하고, 소비자가 가장 단순하다(내부 호출 1곳, deps getter 1개, 문맥 접근자 1개, 외부 소비자 없는 전달 함수 4개). 전달 함수 6개 삭제 + 내부 호출 직접화 + getter·접근자 2개 재지시. 시험: step3 전달 단언 → "등록부로 같은 이름을 찾을 수 있다 + app.js 에 정의가 없다"(단언 수 증가), a2 패널 3명 동일, a5a 브라우저 하네스에 `runHistory` 스텁 배선 추가(단언 수 불변), 기준선 실측 하향(forwarders 174→168).
- **위험·확인**: TDZ — 문맥 접근자·getter 본문이 `runHistory` 를 읽는 시점은 이벤트 시점뿐(모듈 create()는 deps 를 읽지 않음이 a1/a2에서 증명). 수신자 — 6개 메서드 모두 `this` 미사용 확인. 장부로 초기화 순서 변동 감시.

### B7 2차 — sidebar 등록 + closeSidebar allowlist (2026-11-18)

- **allowlist 항목 목록(현시점)**: `syncClawRunHistoryVisibility`(runHistory 소유, B6 리뷰) + `closeSidebar`(CTO 승인, 2026-11-18 — sidebar 모듈이 소유자: app.js 접근자(17행)·1줄 전달 함수(1939행)가 최종 위임하는 대상이 `sidebarModule().closeSidebar` 본인, `this` 미사용). 두 항목 모두 **B7 마지막 단계에서 app.js 접근자를 제거하면 목록에서 뺀다**(목록은 임시 장치).
- **구현**: sidebar 모듈을 원래 팩토리 위치(app.js 176행)에서 `app.provide("sidebar", …)` 등록(실행 순서 불변, 팩토리는 등록부 조각 반환 alias 유지). 전달 함수 4개(sidebarActionIcon·setSidebarCollapsed·closeSidebar·openSidebar) 삭제. 호출자 전환: app.js 내부 3곳(1722·2055·2077행)+wire 1곳(2071행)은 조각 직접 호출, 문맥 접근자(17행)와 history deps getter(216행)는 등록부 값 반환(getter 유지 — deps 표면 불변). deps.sidebarActionIcon 소비자는 history 모듈 4곳.
- **수치**: app.js 2,573 → **2,567**줄, `appjs_forwarders` 168 → **164**, `appjs_function_decls` 226 → **222**. deps·listeners·dom 불변. 기준선 실측 하향.
- **시험(넓히기만)**: step1 전달 단언을 "등록부로 찾을 수 있다 + app.js 에 정의가 없다 + 모듈 조각에 이름이 있다"로 전환(settings 4개는 기존 단언 유지), 등록부 도달성 신규 시험 1건(step1), 가드 시험에 closeSidebar 목록 안 사례 추가, step1 브라우저 하네스를 등록부 경로로 적응, ui_request_speed openSavedConversation 절편 하네스에 sidebar 배선.
- **wire 중복 결정(CTO 06:41)**: sidebar 조각의 `wire` → **`wireSidebarListeners`** 로 변경(다른 조각의 관례 wireViewListeners·wireMemoryListeners·wireRunHistoryListeners에 맞춤). localPcPanel의 `wire`는 그 모듈을 옮기는 차수에서 처리. 변경 범위: 모듈 정의·export, app.js 호출 1곳, step1 이름 목록 — 단언 수·범위 불변. 등록 순서·위치는 원래 팩토리 위치 유지.

### B7 4차 — streaming 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: app.js 를 읽는 chat 정적 계약 시험 중 5개 전달 함수 관련 — (1) test_3531:75 전달 존재 단언 → 등록부 단언으로 전환, (2) test_3935:182 호출점 서브스트링 단언(`requestAnswer(retryMessages, retrySkill` — `streaming.requestAnswer(...)` 전환 후에도 매치) 불변, (3) 절편 경계로 5개 이름을 쓰는 시험 **0건**(모든 .index/.split 경계는 STREAM 모듈 소스). route-ordering 의 `const advancedSettingsView` 경계는 스트리밍 전달 함수(앞쪽)와 무관.
- **구현**: streaming 모듈을 원래 팩토리 위치(app.js:172)에서 `app.provide("streaming", …)` 등록(실행 순서 불변). 전달 함수 5개(requestCompletedAnswer·applyStreamDone·requestStreamingAnswer·cancelActiveStream·requestAnswer) 삭제. 호출자 전환 — app.js 내부 3곳(requestAnswer: 재시도·복구·제출)+cancelStreamButton 리스너는 조각 직접 호출, 스트리밍 deps 리터럴 getter 3개(applyStreamDone·requestCompletedAnswer·requestStreamingAnswer — 모듈이 자기 API를 deps로 재판정하는 형태)는 등록부 값 반환(getter 유지). 조각 5키는 문맥 접근자와 충돌 0(allowlist 불필요), 대상 메서드 this-free(모듈 내 this 2건은 DOM 셈 폴백 객체 메서드로 자기 수신자 호출).
- **수치**: app.js 2,563 → **2,557**줄, `appjs_forwarders` 159 → **154**, `appjs_function_decls` 217 → **212**. deps·listeners·dom 불변. 기준선 실측 하향.
- **시험(넓히기만)**: step5b 모듈·behavior 2종의 전달 단언을 등록부 단언으로 전환(단어 수 증가), 등록부 도달성 신규 시험 1건(step5b 모듈), 3531 적응.

### B7 4차 — streaming 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: app.js 를 읽는 chat 정적 계약 시험 중 5개 전달 함수 관련 — (1) test_3531:75 전달 존재 단언 → 등록부 단언으로 전환, (2) test_3935:182 호출점 서브스트링 단언(`requestAnswer(retryMessages, retrySkill` — `streaming.requestAnswer(...)` 전환 후에도 매치) 불변, (3) 절편 경계로 5개 이름을 쓰는 시험 **0건**(모든 .index/.split 경계는 STREAM 모듈 소스). route-ordering 의 `const advancedSettingsView` 경계는 스트리밍 전달 함수(앞쪽)와 무관.
- **구현**: streaming 모듈을 원래 팩토리 위치(app.js:172)에서 `app.provide("streaming", …)` 등록(실행 순서 불변). 전달 함수 5개(requestCompletedAnswer·applyStreamDone·requestStreamingAnswer·cancelActiveStream·requestAnswer) 삭제. 호출자 전환 — app.js 내부 3곳(requestAnswer: 재시도·복구·제출)+cancelStreamButton 리스너는 조각 직접 호출, 스트리밍 deps 리터럴 getter 3개(applyStreamDone·requestCompletedAnswer·requestStreamingAnswer — 모듈이 자기 API를 deps로 재판정하는 형태)는 등록부 값 반환(getter 유지). 조각 5키는 문맥 접근자와 충돌 0(allowlist 불필요), 대상 메서드 this-free(모듈 내 this 2건은 DOM 셈 폴백 객체 메서드로 자기 수신자 호출).
- **수치**: app.js 2,563 → **2,557**줄, `appjs_forwarders` 159 → **154**, `appjs_function_decls` 217 → **212**. deps·listeners·dom 불변. 기준선 실측 하향.
- **시험(넓히기만)**: step5b 모듈·behavior 2종의 전달 단언을 등록부 단언으로 전환(단어 수 증가), 등록부 도달성 신규 시험 1건(step5b 모듈), 3531 적응. CI 정합성: streaming 브라우저 하네스(deps getter·forwarder 라인을 등록부 경유), route-ordering·rate_limit·3936 vm 하네스에 streaming 스텁 배선(requestAnswer 카운팅 위임).

### B7 5차 — connectors 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 5개 이름(setConnectorCopy·connectorTicketErrorKey·connectorsScope·openConnectorsView·openConnectorsDialog)마다 `grep -rn`으로 app.js를 읽는 시험·절편 경계·리터럴 단언을 목록화. APP 독자 단언 4건(test_r5_a9 모듈 전달 단언, test_7365 라우트 단언, test_4862 라우트 순서 단언, calendar vm 하네스 getter)을 등록부 경로로 적응. 절편 경계 3건(test_7607 커넥터 도우미, test_google_drive `_function`, test_chat_claw_answer_views `definition_source`)은 모듈 소스를 읽어 불변.
- **구현**: connectors 모듈을 원래 팩토리 위치(app.js:2324)에서 `app.provide("connectors", …)` 등록(실행 순서 불변). 전달 함수 5개 삭제. 호출자 전환 — app.js 라우트 복귀·OAuth 복귀 2곳은 조각 직접 호출, calendar deps getter 3개는 등록부 값 반환(getter 유지). 조각 24키는 기존 등록 이름·문맥 접근자와 충돌 0(allowlist 추가 없음), 대상 메서드 this-free.
- **수치**: app.js 2,557 → **2,552**줄, `appjs_forwarders` 154 → **149**, `appjs_function_decls` 212 → **207**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: test_r5_a9 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, 라우트·리터럴 단언 3건 등록부 경로 적응, calendar vm 하네스에 connectors 스텁 배선. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 6차 — nav 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 7개 이름(syncRouteHash·setNavActive·switchConversationProduct·openClawWorkspace·openChatWorkspace·openClawManual·openClawRunTarget)마다 `grep -rn` 전수 조사. APP 독자 단언 8건(a10 모듈 2, chat_screen_polish 창 계약, 4862 라우트, util_app 창 계약, 3936/vm 2, calendar deps vm, ui_request_speed 절편)을 등록부 경로·스텁으로 적응. 절편 경계는 전부 nav 모듈 소스를 읽어 불변.
- **구현**: nav 모듈을 원래 팩토리 위치(app.js:637)에서 `app.provide("nav", …)` 등록(실행 순서 불변). 전달 함수 7개 삭제. 호출자 전환 — 라우트 복귀·창 계약·history/Claw 진입 5곳은 조각 직접 호출, app.js 문맥 접근자 1개(setNavActive)와 deps getter 2개(openClawRunTarget·switchConversationProduct)는 등록부 값 반환(getter 유지). `wireNavRouteListener`·`wireNavEntryListeners`는 원래 자리에서 1회씩 호출.
- **allowlist 5번째 — `setNavActive`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자와 모든 호출자가 nav 모듈의 같은 메서드로 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. B7 마지막 단계에서 app.js 접근자 제거 시 함께 뺀다.
- **수치**: app.js 2,552 → **2,545**줄, `appjs_forwarders` 149 → **142**, `appjs_function_decls` 207 → **200**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: a10 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, 창 계약·라우트·vm 하네스 8건 적응, 문맥 이름 가드에 setNavActive 사례 추가. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 7차 — pcRun 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 7개 이름(showPcRuntimeStatus·waitForAcceptedPcRun·pcWaitElapsed·findUnfinishedPcRun·resumeUnfinishedPcRun·renderStoredPcAnswer·recoverStoredPcResult)마다 `grep -rn` 전수 조사. APP 독자 단언 2건(a3 모듈 전달 단언, 5895 복구 호출 절편)을 등록부 경로로 적응. 5015·4485·5573은 pcRun 모듈 소스를 읽어 불변.
- **구현**: pcRun 모듈을 원래 팩토리 위치(app.js:1791)에서 `app.provide("pcRun", …)` 등록(실행 순서 불변). 전달 함수 7개 삭제. 호출자 전환 — 복구 절편 1곳은 조각 직접 호출, deps getter 6개(streaming 2·pcRun 자체 4)는 등록부 값 반환(getter 유지). 조각 7키는 기존 등록 이름·문맥 접근자와 충돌 0(allowlist 추가 없음), 대상 메서드 this-free.
- **수치**: app.js 2,543(main rebase 기준) → **2,535**줄, `appjs_forwarders` 142 → **135**, `appjs_function_decls` 200 → **193**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향(CSS는 main 값 1,953/1,229 유지).
- **시험(넓히기만)**: a3 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, 5895 절편·ui_request_speed 하네스 배선. allowlist는 5개 그대로.

### B7 8차 — calendar 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 8개 이름(calendarReadStateKey·calendarReadActivationErrorKey·googleCalendarConnectButton·googleCalendarCard·renderCalendarReadState·syncGoogleCalendarConnectButton·beginGoogleCalendarConnect·activateGoogleCalendarRead)마다 `grep -rn` 전수 조사. APP 독자 단언 3건(step2 전달 블록 2·브라우저 하네스 1)을 등록부 경로로 적응. connectors·b54·bright_calendar의 적중은 전부 모듈 deps 스텁으로 불변.
- **구현**: calendar 모듈을 원래 팩토리 위치(app.js:181)의 lazy 생성 블록 안에서 `app.provide("calendar", …)` 등록 — 생성 시점과 deps 표면을 그대로 유지. 전달 함수 8개 삭제. 호출자 전환 — connectors deps getter 4개는 등록부 값 반환(getter 유지). 조각 9키(전달 8 + `calendarServerGrantSessionState`)는 기존 등록 이름·문맥 접근자와 충돌 0(allowlist 추가 없음), 대상 메서드 this-free.
- **수치**: app.js 2,535 → **2,527**줄, `appjs_forwarders` 135 → **127**, `appjs_function_decls` 193 → **185**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: step2 deps 하네스를 등록부 조각 블록으로 전환, 도달성 신규 시험 1건, 브라우저 하네스를 등록부 조회로 적응. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발. allowlist는 5개 그대로.

### B7 9차 — loginDialog 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 8개 이름(setAuthFormError·syncAuthDialogMethods·openAuthDialog·closeAuthDialog·authServerUnreachableError·passwordAuthAnswer·passwordAuthRequest·setAuthStatusMessage)마다 `grep -rn` 전수 조사. APP 독자 단언은 step4 브라우저 하네스 전달 추출과 stage0 전달 위치 단언 2건 — 등록부 경로로 적응. step4 모듈·golden·connectors·streaming의 적중은 전부 deps 스텁으로 불변.
- **구현**: login-dialog 모듈을 원래 팩토리 위치(app.js:385)의 lazy 생성 블록 안에서 `app.provide("loginDialog", …)` 등록(생성 시점 불변). 전달 함수 8개 삭제. 호출자 전환 — app.js 문맥 접근자 4개와 auth deps getter 2개는 등록부 값 반환(getter 유지), 라우트 복귀 1곳은 조각 직접 호출. 조각 15키(전달 8 + 자체 DOM·wire 7) 중 문맥 접근자와 겹치는 4개를 allowlist에 추가.
- **allowlist 6~9번째 — `setAuthFormError`·`syncAuthDialogMethods`·`openAuthDialog`·`closeAuthDialog`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 모두 login-dialog 모듈의 같은 메서드로 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. B7 마지막 단계에서 접근자 제거 시 함께 뺀다. 현재 allowlist 9개.
- **수치**: app.js 2,527 → **2,511**줄, `appjs_forwarders` 127 → **119**, `appjs_function_decls` 185 → **177**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: step4 모듈·브라우저 하네스를 등록부 조회로 전환, 등록부 도달성 신규 시험 1건, stage0 절편 경계 적응, 문맥 가드에 4개 이름 추가. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 10차 — history 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 12개 이름(renderTyping·clearHistoryUI·renderHistorySkeleton·renderHistoryLoadFailed·fetchRecentConversations·loadRecentConversations·clearHistoryActionStatus·showHistoryActionStatus·patchConversation·focusHistoryConversation·beginConversationRename·deleteConversation)마다 `grep -rn` 전수 조사. APP 독자 참조는 app.js 문맥 접근자 1개(loadRecentConversations), streaming deps getter 1개(renderTyping), 세션 바인딩 1곳(clearHistoryUI) — 모두 등록부 경로로 적응. step3 브라우저 하네스의 전달 추출도 등록부 조회로 전환.
- **구현**: history 모듈을 원래 팩토리 위치(app.js:203)의 lazy 생성 블록 안에서 `app.provide("history", …)` 등록(생성 시점 불변). 전달 함수 12개 삭제. 조각 13키(전달 12 + `wireMenuListeners`)는 기존 등록 이름과 충돌 0. 대상 메서드 this-free.
- **allowlist 10번째 — `loadRecentConversations`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 history 모듈의 같은 메서드로 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. 현재 allowlist 10개.
- **수치**: app.js 2,511 → **2,491**줄, `appjs_forwarders` 119 → **107**, `appjs_function_decls` 177 → **165**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: step3 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, step3 브라우저 하네스 등록부 조회, 문맥 가드에 loadRecentConversations 추가. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 11차 — auth 등록 (2026-11-18)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 12개 이름(closeProfilePanel·accountInitial·resolveSessionPresentation·setLoginButtonCopy·applyAuthState·authMethodEnabled·loadAuthStatus·requireSessionForModelUse·signOutCurrentAccount·invalidateClawApprovalSession·noteClawApprovalSession·reviewedGoogleAuthorizationUrl)마다 `grep -rn` 전수 조사. APP 독자 참조는 문맥 접근자 4개·account deps getter 4개·직접 호출 5곳·창 공개 계약 1곳 — 전부 등록부 경로로 적응. step4 브라우저 하네스와 4488·b54·7780·5479·google_drive 절편도 같은 경로로 갱신.
- **구현**: auth 모듈을 원래 팩토리 위치(app.js:219)의 lazy 생성 블록 안에서 `app.provide("auth", …)` 등록(생성 시점 불변). 전달 함수 12개 삭제. 조각 18키(전달 12 + 자체 헬퍼 3 + wire 3)는 기존 등록 이름과 충돌 0. 대상 메서드 this-free.
- **allowlist 11~14번째 — `closeProfilePanel`·`authMethodEnabled`·`loadAuthStatus`·`reviewedGoogleAuthorizationUrl`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 auth 모듈의 같은 메서드로 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. 현재 allowlist 14개.
- **수치**: app.js 2,491 → **2,478**줄, `appjs_forwarders` 107 → **95**, `appjs_function_decls` 165 → **153**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향(CSS는 main 값 1,930/1,219).
- **시험(넓히기만)**: step4 모듈·브라우저 하네스를 등록부 조회로 전환 + auth 도달성 신규 시험 1건, 문맥 가드에 4개 이름 추가, 4488·b54·7780·5479·google_drive·step5 하네스 배선. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 12차 — core 등록 (2026-11-19)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 14개 이름(uiT·idleNote·setNote·hwpLegacyGuidance·formatClockTime·formatBytes·extensionOf·documentMediaType·readAsText·readDocumentFile·selectImage·mappedUiError·clawT·localeOr)마다 `grep -rn` 전수 조사. APP 독자 참조는 문맥 접근자 5개(uiT·clawT·mappedUiError·idleNote·setNote)·deps getter 6개(conversation 5·clawStatus 1)·app.js 직접 호출 약 90곳(대부분 `coreModule().uiT`·`setNote`·`mappedUiError`·`clawT`) — 전부 등록부 경로로 적응. 4379·attachments·browser_streaming 절편 경계는 모듈 소스를 읽어 불변. 3935· plain_korean_error_display 하네스 절편과 ui_request_speed·b54 라우팅 하네스에 core registry 스텁을 배선했다.
- **구현**: core 모듈을 원래 팩토리 위치(app.js:143)의 lazy 생성 블록 안에서 `app.provide("core", …)` 등록(생성 시점 불변). 전달 함수 14개 삭제. 조각 14키는 기존 등록 이름과 충돌 0. 대상 메서드 this-free(모듈 내 `this`는 문자열·주석뿐).
- **allowlist 15~19번째 — `uiT`·`clawT`·`mappedUiError`·`idleNote`·`setNote`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 core 모듈의 같은 메서드와 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. 현재 allowlist 19개.
- **수치**: app.js 2,478 → **2,464**줄, `appjs_forwarders` 95 → **81**, `appjs_function_decls` 153 → **139**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: step7(a7) 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, 문맥 가드에 5개 이름 추가, 위 문자열 단언·절편 12파일 적응, 3935·plain_korean 하네스에 core 스텁 배선. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 13차 — clawRun 등록 (2026-11-19)

- **착수 전 스윕(CTO 요구)**: 삭제 대상 15개 이름(setClawDocumentAction·clearClawArtifact·formatClawBytes·renderClawArtifactMeta·safeClawErrorMessage·downloadClawArtifact·revealClawCard·setApprovalControlsBusy·renderClawApprovalControls·clearImmediateApprovalControls·applyImmediateApprovalDecision·renderClawRequestEcho·clawClaimDispatchKey·releaseClawDispatchKey·runClawExecution)마다 `grep -rn` 전수 조사. APP 독자 참조는 문맥 접근자 2개(downloadClawArtifact·renderClawApprovalControls)·clawForm deps getter 4개(clearClawArtifact·renderClawRequestEcho·revealClawCard·runClawExecution)·부팅 직접 호출 1곳(clearClawArtifact) — 전부 등록부 경로로 적응. b62_2322의 APP 이름 단언 1건과 a2 접근자 형태 단언은 등록부 단언으로 전환. 4차 교훈에 따라 app.js 전체를 읽는 시험의 리터럴·절편 경계도 선행 확인(충돌 0).
- **구현**: clawRun 모듈을 원래 팩토리 위치(app.js:2019)의 즉시 생성 블록 안에서 `app.provide("clawRun", …)` 등록(생성 시점 불변). 전달 함수 15개 삭제. 조각 15키(전달 15와 동일) 중 문맥 접근자와 겹치는 2개를 allowlist에 추가. 대상 메서드 15개 전부 this-free.
- **allowlist 20~21번째 — `downloadClawArtifact`·`renderClawApprovalControls`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 clawRun 모듈의 같은 메서드로 위임 ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. 현재 allowlist 21개.
- **수치**: app.js 2,464 → **2,454**줄, `appjs_forwarders` 81 → **66**, `appjs_function_decls` 139 → **124**. deps 161·listeners 44·dom 133 불변. 기준선 숫자 3줄만 하향.
- **시험(넓히기만)**: a5a 모듈 전달 단언을 등록부 단언으로 전환 + 도달성 신규 시험 1건, a5a 브라우저 하네스를 등록부 미러로 전환(clawRunModule() → app.provide("clawRun"), 대상 15명 대역 생성), 문맥 가드에 2개 이름 추가, b62_2322·a2 접근자 형태 적응. 뮤테이션 2건(provide 제거, 조각 API 누락) 적발.

### B7 14차 — clawStatus 등록(재시도·복구·대기 11개) (2026-11-20)

- **단위표 조정**: clawStatus 전달 함수는 19개라 CTO 상한(10~15개)을 넘으므로 기능 덩어리로 둘로 나눈다. 14차는 모듈 주석의 구획("Claw status, pre-dispatch retry, and the in-flight elapsed wait") 가운데 재시도·복구·대기 덩어리 11개(clawRetryRemaining·clawRetryAfterFromResponse·isAmbiguousClawFailure·clearClawRecovery·renderClawRetryBox·beginClawRetryCooldown·showClawAmbiguousRecoveryHint·applyClawWaitStageCopy·renderClawWait·beginClawWait·clearClawWait), 작곡·상태 전파 4개(syncComposerForClaw·setClawStatus·setClawAreaState·setClawButtonsBusy)와 실행 전 판단 4개(clawVisibleExecutePayload·clawExecuteWireKey·clawCurrentDispatchIsUncertain·noteClawContentEdited)는 다음 차. 15차 account 19도 같은 방식으로 나눈다.
- **착수 전 스윕(CTO 요구)**: 삭제 대상 11개 이름 grep 전수 조사. APP 독자 참조는 공유 문맥 접근자 2개(clearClawWait·clearClawRecovery)·clawRun deps getter 6개(clawRetryRemaining·clawRetryAfterFromResponse·isAmbiguousClawFailure·beginClawRetryCooldown·showClawAmbiguousRecoveryHint·beginClawWait)·localechange 리스너 직접 호출 3곳(renderClawWait·applyClawWaitStageCopy·renderClawRetryBox)·PadiemClawSession.bind 값 2개(clearRecovery·clearWait) — 전부 등록부 경로로 적응. 대상 메서드 11개 전부 this-free(모듈 본문 정규식 스캔 0건). 조각 19키 중 공유 접근자와 겹치는 이름은 5개(setClawStatus·setClawAreaState·setClawButtonsBusy·clearClawRecovery·clearClawWait).
- **구현**: clawStatus 모듈을 원래 팩토리 위치(app.js:2045)의 즉시 생성 블록 안에서 `app.provide("clawStatus", …)` 등록(생성 시점 불변). 등록 핸들은 DOM 요소 const `clawStatus`(app.js:2058)와의 충돌을 피해 기존 인스턴스 이름 `clawStatusModuleInstance`를 유지(calendar·history·nav·pcRun 선례) — 접근자 함수 `clawStatusModule()`은 그대로고 나머지 8개 전달 함수도 유지된다. 전달 함수 11개 삭제, 호출자 전환: 공유 접근자 2개·clawRun deps getter 6개는 `clawStatusModule().<이름>` 반환, 리스너 직접 호출 3곳·세션 bind 2값은 등록부 경유 호출.
- **allowlist 22~26번째 — `setClawStatus`·`setClawAreaState`·`setClawButtonsBusy`·`clearClawRecovery`·`clearClawWait`** (CTO 승인 + 상시 승인 3조건 충족): ① app.js 접근자가 clawStatus 모듈의 같은 메서드로 위임(전달 함수 경유 포함 — 2차 closeSidebar 선례) ② 메서드가 `this` 미사용 ③ 모듈을 원래 팩토리 위치에서 등록. 현재 allowlist 26개. B7 임시 — 마지막 단계에서 app.js 접근자 제거 시 목록에서 뺀다.
- **수치**: app.js 2,454 → **2,450**줄, `appjs_forwarders` 66 → **55**, `appjs_function_decls` 124 → **113**. deps 161·listeners 44·dom 133 불변.
- **시험(넓히기만) + 기존 파손 복구**: a4 모듈 전달 단언을 등록부 단언으로 전환(REGISTRY_NAMES 11은 app.js 정의 없음 + 도달성 신규 1건, FORWARDER_NAMES 8은 기존 형태 유지). a4·a5a 브라우저 하네스가 **B6(#7938) 때부터 로컬에서 수집조차 못 했다** — B6가 deps 블록을 `Object.setPrototypeOf({...}, app)` 형태로 바꾸면서 하네스의 `"\n  });"` 절편 경계가 create 블록 끝을 못 찾아 DOM const 구역까지 overshoot, 페이지 const 재선언 SyntaxError(`window.__exercise is not a function`). CI 브라우저 레인이 이 두 파일을 선택하지 않아 잠복했다. 14차에서 절편 경계를 실제 블록 끝(`"\n  }, app)));")로 좁히고(app stub=provide 미러+proto 접근자 14·24개, clawStatus 조각 스텁), 단언은 그대로 유지 — 두 하네스 모두 실제 Chromium에서 처음으로 녹색. 원문 단언 래칫(#8073)이 문장 수를 세므로 신규 단언은 기존 루프 형태(문장 1개)로 합쳐 base 이하 유지(8→8).
- **검증**: 래칫 4종(#8058·#8073·#8065·#8087) 13 passed — head가 base를 안 넘는다. 부팅 장부 3회×2폭+증분(main 42·branch 18 샘플): 구조 해시·리스너 다중집합·요청 주소·창 이름 변형 풀 일치. ±1 DOMContentLoaded 레이스와 장치 디렉터리 스냅샷 레이스(PadiemClawDeviceDirectory 없는 변형)는 양쪽 트리에서 모두 재현되는 base 자체 변이(장비 스크립트 4개는 이동 이름 참조 0). 골든 로그인 5경로 main/branch byte-identical. 뮤테이션 2건 적발(provide 제거→구조 계약 실패, 조각 API 누락→vm·브라우저·도달성 3건 실패). e2e 14 passed. 광역 스위트 14,639 passed+42 failed — 31 실패 파일을 main·branch 격리 재실행한 결과 시험 단위까지 동일(기존 실패, a3/a9 브라우저 하네스는 같은 B6 절편 가족). 머지·배포 없음 — CTO 승인 후 머지.

### B7 15차 — clawStatus 등록 완료(잔여 8개) (2026-11-20)

- **범위**: 14차에 이어 clawStatus 잔여 8개(syncComposerForClaw·setClawStatus·setClawAreaState·setClawButtonsBusy·clawVisibleExecutePayload·clawExecuteWireKey·clawCurrentDispatchIsUncertain·noteClawContentEdited)를 삭제해 clawStatus 등록을 완료한다. account 19는 기능 덩어리(비밀번호 재설정+변경 12 / 계정 삭제 7)로 나눠 16차·17차에서 처리.
- **착수 전 스윕(CTO 요구)**: 8개 전부 this-free. app.js 호출부는 공유 접근자 3(setClawStatus·setClawAreaState·setClawButtonsBusy — 14차 allowlist 등재분)·nav deps getter 1(syncComposerForClaw)·clawRun deps getter 3(clawCurrentDispatchIsUncertain·clawVisibleExecutePayload·clawExecuteWireKey)·clawForm deps getter 1(noteClawContentEdited)·부팅 직접 호출 2(localechange syncComposerForClaw·부팅 setClawAreaState("idle")). allowlist 추가/제거 0.
- **구현**: 전달 함수 8개 삭제, 호출자 10곳을 `clawStatusModule().<이름>` 경유로 전환. b62_2532·a5b 단언은 전환 후에도 원문이 살아 무변경, b62_2483 절편 앵커 1건(`function setClawStatus` 소멸)만 `function clawStatusModule`로 교체.
- **수치**: app.js 2,450 → **2,440**줄, `appjs_forwarders` 55 → **47**, `appjs_function_decls` 113 → **105**. deps 161·listeners 44·dom 133 불변.
- **시험(넓히기만)**: a4 모듈 REGISTRY_NAMES를 19개로 확장(FORWARDER_NAMES 소멸), a4 브라우저 하네스 주석 갱신, a5a 브라우저 하네스의 clawStatus 조각 스텁에 deps getter가 등록부 경유로 읽는 3개 추가. 원문 단언 문장 수 감소(래칫 안전).
- **검증**: 래칫 4종 13 passed. 부팅 장부 변형 풀 일치(main 30·branch 6 샘플 — branch 변형 3종 전부 main 풀에 포함, 신규 변형 0). 골든 5경로 byte-identical. 뮤테이션 2건 적발(provide 제거→구조 계약, setClawStatus 조각 누락→도달성·vm·브라우저 3건). e2e 14 passed. 광역 스위트 14,638 passed+142 failed — 실패 142건 중 127건은 14차 스위트와 동일 목록, 나머지 15건(전체 스위트 문맥 오염 플레이크)은 5파일을 main·branch 격리 재실행에서 84/84 전부 통과로 귀속 확인 — 신규 실패 0. 머지·배포 없음 — CTO 승인 후 머지.

### B7 16차 — account 비밀번호 재설정+변경 12개를 등록부로 (2026-11-20)

- **범위**: account 19 중 비밀번호 재설정+변경 덩어리 12개(passwordResetTokenFromLocation·clearPasswordResetFragment·showPasswordResetView·hidePasswordResetViews·openPasswordResetRequest·openPasswordResetConfirm·closePasswordResetViews·submitPasswordResetRequest·submitPasswordResetConfirm·openPasswordChangeDialog·closePasswordChangeDialog·submitPasswordChange)를 등록부로 옮긴다. 계정 삭제 7은 17차에서 처리. 선정 이유: 15차 계획(기능 덩어리 분할, 상한 15)대로 비밀번호 덩어리는 재설정 메일 링크→요청→확인→변경의 독립 기능군이고, 삭제 덩어리는 별도 확인 단계·공유 계정 경로를 가져 다음 차로 분리한다.
- **착수 전 스윕**: 12개 전부 this-free. app.js 호출부는 loginDialog deps getter 1(passwordResetTokenFromLocation)·부팅 직접 호출 1(resetLinkOnLoad)뿐. 공유 접근자 충돌 0 → allowlist 추가/제거 0(27개 유지). 등록 이름 충돌은 조각의 `wire` 키가 localPcPanel의 `wire`와 중복 1건 → 내보내기 이름을 `wireAccountControls`로 변경(내부 함수 이름 wire 유지, 유일 호출부 app.js 부팅도 함께 전환).
- **구현**: 원래 lazy 팩토리 블록 안에서 `app.provide("account", …)` 등록(accountModule() 첫 호출 = 부팅 wire 자리, 생성 시점·순서 불변). 전달 함수 12개 삭제, #5434 주석은 모듈 submitPasswordChange 위로 이관. deps getter·부팅 호출은 등록부 경유로 전환.
- **수치**: app.js 2,440 → **2,420**줄, `appjs_forwarders` 47 → **35**, `appjs_function_decls` 105 → **93**. deps 161·listeners 44·dom 133 불변. 원문 단언 수 13,199 불변.
- **시험(넓히기만)**: step4 모듈 전달 단언을 등록부 단언으로 전환(ACCOUNT_REGISTRY_NAMES 12: app.js 정의 없음+조각 이름 존재)+provide("account") 구조 단언+도달성 신규 1건. step4 브라우저 하네스에 account 조각 provide 미러+등록부 라우팅 12 추가(추출 전달 함수 39→27). a6 androidHandoff 절편 앵커 1건 교체(`accountModule().wire()` 소멸 → `wireAccountControls()`, 등록 순서 단언 유지).
- **검증**: 래칫 4종 13 passed+파일 가드 5. 부팅 장부 변형 풀 일치(main 30·branch 6 샘플 — branch 변형 3종 전부 main 풀 포함, 신규 변형 0; ±1 DOMContentLoaded·noDevDir 레이스는 base 변이). 골든 로그인 5경로 byte-identical, account 골든 일치. 뮤테이션 2건 적발(provide 제거→구조 계약 1건, submitPasswordChange 조각 누락→구조·도달성·vm 골든·브라우저 4건+fixture 연쇄 10). e2e 14 passed, 오프라인 레인 node --test 74+pytest 13 passed. 머지·배포 없음 — CTO 승인 후 머지.

### B7 17차 — account 계정 삭제 7개를 등록부로, account 등록 완료 (2026-11-20)

- **범위**: account 잔여 계정 삭제 7개(resetAccountDeleteConfirm·resetAccountSharedDeleteConfirm·openAccountDeleteConfirm·openAccountSharedDeleteConfirm·syncAccountDeleteButton·syncAccountSharedDeleteButton·submitAccountDelete) 전달 함수를 삭제해 account 등록을 완료한다. account 모듈에 남은 전달 함수가 없어 17차는 7개(상한 15 이내, 다른 모듈 혼합 없음). 삭제 덩어리는 별도 확인 단계(이메일 정확히 일치)와 공유 계정(all-service) 경로가 있어 본문은 모듈에 그대로 두고 연결 경로만 바꾼다.
- **착수 전 스윕**: 7개 전부 this-free. app.js 호출부는 auth deps getter 1(resetAccountDeleteConfirm — chat-auth-module applyAuthState가 소비)뿐. 공유 접근자 충돌 0 → allowlist 추가/제거 0(27개 유지). 7개 이름은 16차 app.provide("account") 조각에 이미 등록되어 있어 신규 등록 불필요.
- **구현**: 전달 함수 7개 삭제, auth deps getter를 등록부 경유로 전환. 삭제 확인 주석은 모듈 resetAccountDeleteConfirm 위로 이관. 생성 시점·순서 불변(account 첫 호출 = 부팅 wire 자리).
- **수치**: app.js 2,420 → **2,403**줄, `appjs_forwarders` 35 → **28**, `appjs_function_decls` 93 → **86**. deps 161·listeners 44·dom 133 불변. 원문 단언 수 13,199 불변.
- **시험(넓히기만)**: step4 모듈 ACCOUNT_REGISTRY_NAMES를 19개로 확장(전달 함수 분기 소멸, 미분류 이름 가드 추가), 도달성 19개 커버. step4 브라우저 하네스 등록부 라우팅 19(추출 전달 함수 27→20).
- **검증**: 래칫 4종 13 passed+파일 가드 5. 부팅 장부 변형 풀 일치(main 30·branch 6 샘플 — branch 변형 4종 전부 main 풀 포함, 신규 변형 0). 골든 로그인 5경로 byte-identical, account 골든 일치. 뮤테이션 2건 적발(provide 제거→구조 계약 1건, submitAccountDelete 조각 누락→구조·도달성·vm 골든·브라우저 4건). e2e 14 passed, 오프라인 레인 node --test 74+pytest 13, 계정 삭제 백엔드 시험 47 passed. 머지·배포 없음 — CTO 승인 후 머지.

### B7 18차 — conversation 첨부 덩어리 8개를 등록부로 (2026-11-20)

- **범위**: 남은 전달 함수 28개(conversation 19·androidHandoff 9) 중 conversation의 첨부 8개(attachmentCopy·clearAttachment·attachmentCountLimit·attachmentTrayNote·removeAttachmentItem·renderAttachmentChips·addAttachmentFiles·attachmentPayload)를 등록부로 옮긴다. 선정 이유: androidHandoff 9는 이슈 기록상 보류 유지(세션 스토리지 경계·stage0 계약), conversation 19는 상한 15 초과 → 기능 덩어리 분할. 첨부 덩어리는 파일 첨부 UI(복사·제한·트레이·칩·추가·제거·페이로드·해제)의 자족적 기능군으로 상한 이내다. 다른 모듈은 섞지 않는다.
- **착수 전 스윕**: 8개 전부 this-free(모듈 전체 this 0). 호출부는 공유 접근자 1(attachmentCopy)+conv deps getter 4·streaming deps getter 1(attachmentPayload)+부팅직접 5(clearAttachment 3·addAttachmentFiles 2)뿐. 조각 20키 중 공유 접근자 충돌 6개(approvedMemoryErrorMessage·attachmentCopy·renderStreamError·resetConversationView·safeLocalUiMessage·updateComposer) → allowlist 27→34(+6). 상시 승인 3조건 충족: 같은 모듈 메서드 위임(accessor→forwarder→모듈 메서드, 2차 closeSidebar 선례)·this-free·원래 lazy 팩토리 위치 등록.
- **구현**: 원래 lazy 팩토리 블록 안 app.provide("conversation") 등록(생성 시점·순서 불변), 전달 함수 8개 삭제+호출자 11곳 등록부 경유 전환. allowlist 6개 등재 주석에 근거 명시.
- **수치**: app.js 2,403 → **2,398**줄, `appjs_forwarders` 28 → **20**, `appjs_function_decls` 86 → **78**. deps 161·listeners 44·dom 133 불변. 원문 단언 수 13,199 불변(신규 등록부 단언은 기존 문장에 합쳐 증가 억제).
- **시험(넓히기만)**: step5 모듈 전달 단언 REGISTRY 8/FORWARDER 11 분리+도달성 신규 1건+provide 구조 단언(기존 문장에 결합), step5 브라우저 하네스 app.provide 미러+등록부 라우팅 8(추출 전달 19→11), 스트리밍 계약 절편 앵커 1건 교체(`function clearAttachment` 소멸→`clearProjectsUI`, 단언 유지), ui_request_speed 절편 하네스에 conversation 등록부 스텁 1건 추가(같은 clearAttachment 스텁 미러).
- **검증**: 래칫 4종 13 passed+파일 가드 5, 부팅 장부 변형 풀 일치(main 30·branch 6 샘플, 신규 변형 0), 골든 로그인 5경로 byte-identical+account 골든 일치, 뮤테이션 2건 적발(provide 제거→구조 2건, clearAttachment 조각 누락→도달성·브라우저 5건+fixture 연쇄 18), e2e 14 passed, 오프라인 node --test 74+pytest 13, 스트리밍 계약 13 passed. 머지·배포 없음 — CTO 승인 후 머지.

### B7 19차 — conversation 잔여 11개를 등록부로, conversation 등록 완료 (2026-11-20)

- **범위**: 18차 첨부 8개에 이어 conversation 잔여 11개(showComposerInlineHint·updateComposer·showConversation·addUserMessage·renderAnswer·renderStreamError·safeLocalUiMessage·resetConversationView·resetConversation·approvalDecisionErrorMessage·approvedMemoryErrorMessage) 전달 함수를 삭제해 **conversation 등록을 완료**한다(11개, 상한 15 이내, 다른 모듈 미혼합). androidHandoff 9는 이슈 기록대로 보류 유지.
- **allowlist 변동 0(34개 유지)**: 19차 대상의 공유 접근자 충돌 5개(approvedMemoryErrorMessage·renderStreamError·safeLocalUiMessage·resetConversationView·updateComposer)는 18차에서 이미 상시 승인 3조건(같은 모듈 메서드 위임·this-free·원래 위치 등록) 충족으로 등재돼 신규 추가 불필요. 18차 등록 근거 주석 그대로 유지.
- **착수 전 스윕**: 11개 전부 this-free(모듈 전체 this 0). 호출부는 공유 접근자 5·deps getter 3(renderAnswer·approvalDecisionErrorMessage·resetConversation)·부팅/리스너 직접 호출 다수(showComposerInlineHint 2·updateComposer 4+입력 리스너·showConversation 2·addUserMessage 2·safeLocalUiMessage 1·resetConversationView 2+세션 bind·resetConversation 1).
- **구현**: 등록 자체는 18차 app.provide("conversation") 유지(생성 시점·순서 불변), 전달 함수 11개 삭제+호출자 전환(입력 리스너는 `(event) => conversationModule().updateComposer(event)` 형태로 인자 보존).
- **수치**: app.js 2,398 → **2,385**줄, `appjs_forwarders` 20 → **9**, `appjs_function_decls` 78 → **67**. deps 161·listeners 44·dom 133 불변. 원문 단언 수 13,199 불변.
- **시험(넓히기만)**: step5 REGISTRY 19/FORWARDER 소멸(도달성 19 커버), 브라우저 하네스 라우팅 19(추출 전달 소멸). 절편 하네스 4건 적응 — 스트리밍 계약 renderCancelled 앵커, plain_korean_cjs renderCancelled 앵커, ui_request_speed conversation 스텁 확장(showConversation/addUserMessage), e2e 3098 renderStreamError 로컬 미러, static UI contract에서 발견된 5파일 추가 적응(test_4422·test_projects resetConversation 단언, test_4469 CLAW_BOUNDED 앵커, test_b54 route-ordering conversation 스텁 4개, test_r5_a2 공유 접근자 2개 형태). 모두 단언 유지.
- **검증**: 래칫 4종 13 passed+가드 5, 부팅 장부 변형 풀 일치(main 30·branch 6 샘플, 신규 변형 0), 골든 로그인 5경로 byte-identical+account 골든 일치, 뮤테이션 2건 적발(provide 제거→구조·하네스 2건, showConversation 조각 누락→도달성·브라우저 2건+fixture 연쇄 18), e2e 14 passed, 오프라인 node --test 74+pytest 13, ui_request_speed 5 passed. 머지·배포 없음 — CTO 승인 후 머지.

### B7 20차 — androidHandoff 잔여 9개를 등록부로, B7 등록 이관 완료 (2026-11-20)

- **보류 사유 확인**: #7812 대표 결정(261116)은 "안드로이드 작업 때까지 T2에서 옮기지 않는다"는 일정상 보류였고, 코드상 경계는 R-06(세션 스토리지 reader/writer와 resumeAndroidHandoff는 app.js 소유, 모듈에 sessionStorage 접근 0)과 stage0 TDZ 제약(`let androidHandoffModuleInstance`가 wire 호출 1906·resume 정의 1493보다 앞)이었다. 9개 전달 함수 자체는 이 경계에 해당하지 않는다.
- **생성·호출 시점 표(9개 공통)**: 레지스트리 `app`은 app.js 첫 문장(8줄)에 생성된다. 모듈 인스턴스는 lazy factory가 처음 호출되는 부팅 1906줄(`wireAndroidHandoffListeners()`)에 생성되며, 이는 등록부 생성(8줄) 이후다. 개별 호출부: isAndroidWebView(resume 1494·loginDialog deps getter), renderAndroidHandoff(resume 1503·localechange 1931·deps getter), startAndroidHandoffPolling(resume 1504), pollAndroidHandoff(resume 1505), startAndroidHandoff(deps getter), clearAndroidHandoff(session bind 2272), stopAndroidHandoffPolling·androidHandoffPhaseKey·claimAndroidHandoff(app.js 호출부 없음 — 모듈 내부 전용). 전부 등록부 생성 이후 호출되고 조각 키 충돌 0·this-free → **9개 전부 옮김**(강제 잔여 0).
- **구현**: 원래 lazy factory 자리에서 `app.provide("androidHandoff", create(...))` 감싸기(생성 시점·순서 불변), 전달 함수 9개 삭제, 호출자 전환(deps getter 3·resume 4·localechange 1·session bind 1).
- **allowlist 변동 0(34개 유지)**: 조각 10키가 공유 접근자·타 모듈 조각과 충돌 0.
- **수치**: app.js 2,385 → **2,378**줄, `appjs_forwarders` 9 → **0**(B7 완료), `appjs_function_decls` 67 → **58**. deps 161·listeners 44·dom 133 불변. 원문 단언 수 13,167 불변.
- **시험(넓히기만)**: a6 전달 단언을 등록부 단언으로 전환+도달성 신규 1건, sessionStorage/TDZ/wire 순서 단언 유지.
- **검증**: 래칫 4종 13 passed+가드 5, 부팅 장부 변형 풀 일치(main 30·branch 6 샘플, 신규 변형 0 — 시점 불변 증거), 골든 로그인 5경로 byte-identical+account 골든 일치, 뮤테이션 2건 적발(provide 제거→구조 1건, isAndroidWebView 조각 누락→구조·vm·도달성 3건), a6 8 passed, e2e 14, 오프라인 node --test 74+pytest 13, ui_request_speed 5 passed.


### T2 follow-up card 1: document formats menu listeners (2026-11-25)

- Scope: conversation-owned document formats menu only. The original listener block now invokes conversationModule().wireDocumentFormats() at the same position, preserving listener registration order; no copy/UI changes.
- Moved into chat-conversation-module.js: two DOM lookups (documentFormatsToggle, documentFormatsPanel), two click listeners (toggle, document), and unchanged visibility/aria-expanded handling. No shared state or deps.
- Metrics (main to branch): appjs_lines 2378 -> 1783; appjs_dom_lookups 133 -> 131; appjs_listeners 44 -> 42; appjs_deps_total 161 -> 161; appjs_forwarders 0 -> 0.
- Direct contract: strict deps create() does not read deps, wireDocumentFormats() registers listeners, toggle/outside/inside clicks retain the original behavior.
- Baseline mechanism: current main has no committed structure_baseline.json (#8054), so the existing main/head structural ratchet remains unchanged.
### 프로젝트 영역 통째 이동 — #7812 (2026-11-26)

- **범위**: 프로젝트 목록·선택·대화상자·프로젝트 파일 함수 23개를 `chat-project-module.js`로 이동. 모듈 전용 DOM·상태 선언은 `create()`, 리스너 14개는 `wireProjectListeners()`에 두고 app.js는 등록·마운트·wire 호출만 유지한다. 동작·문구·화면 변경은 없다.
- **수치**(`chat_structure_audit.py`, main `1231983a1b` → head): `appjs_lines` 2378 → 1783, `appjs_dom_lookups` 133 → 103, `appjs_listeners` 44 → 30, `appjs_function_decls` 58 → 35, `appjs_forwarders` 0 → 0, `appjs_deps_total` 161 → 154. `index_script_tags` 136 → 137은 새 모듈 1개라 래칫 제외 항목이다.
- **본문 동등성**: 23/23 일치. 의존성 주입(`deps.`·기존 모듈 팩토리 호출), `create()`로 올린 `drivePanel` 선언 1개, 줄바꿈·공백을 정규화했다. 원문 함수 선언 집합의 차이는 23개이고 모듈에 없는 삭제 함수는 0개다.
- **시험**: 바뀐 38개 pytest 파일 408 passed. 신규 계약 6개는 strict deps 생성·wire 순서·직접 동작·`projectById` 뮤테이션 실패를 확인한다. 기존 원문 단서는 읽는 대상을 모듈로 옮기거나 프로젝트 모듈 전체로 확대해 강도를 유지했다.
- **브라우저 회귀 수리**: `fetch`를 `deps` 메서드로 넘길 때 `this`가 달라지는 문제를 `fetch.bind(window)`로 수정했다. 기존 auth-loss 브라우저 계약과 프로젝트 QA가 회귀를 재현했고, 수정 후 main과 branch를 같은 조건으로 비교한다.
- **CI 정적 계약 적응**: 전체 pytest에서 드러난 7개 실패는 프로젝트·네비·Claw 상태 모듈로 읽기 대상과 레지스트리 스텁을 옮겨 복구했다. route inventory에는 프로젝트 모듈을 추가했다. main에서도 동일하게 실패하는 council entry 계약 1건은 이 변경의 범위 밖이다.
- **구조 래칫**: exact main 기준 13 passed, 늘어난 비교 수치 0.
- **부팅 장부**: 외부 Windows 측정 호스트가 Tailscale 오프라인이라 1440·390 재측정은 미실행이다. 측정 완료 전에는 통과로 보고하지 않는다.

### #7809 T2 stage 2 (2026-11-27)

- app.js: 1783 -> 1598 lines. Existing conversation registry owns 13 additional functions: lifecycleForError, addAssistantShell, renderStoredAssistant, renderWebGroundingNotice, clawBoundedRefusalCopy, clawGeneralFailure, buildRetryBox, revealErrorState, failureCodeNote, failureStatusLabel, renderError, renderCancelled, handleCustomRequestFailure.
- Constants moved with their consumers: CLAW_BOUNDED_REFUSAL_COPY, CUSTOM_AUTH_FAILURE_CODE, FAILURE_CODE_PATTERN.
- Existing live app context getter/setter for activeProject is reused; the retry test verifies the original closure state and project rendering observe retryContext.project. No new global.
- tools/verify_7809_t2_stage2.py compares all 13 definitions with the base after only explicit dependency-reference substitutions, plus exact constant comparisons.


### #7809 T2 stage 3 (2026-11-27)

- Entry module: `chat-entry-module.js` owns `openSavedConversation` (57 lines), `clawGeneralRequestActive` (3), `storedRegenerateRequest` (11), and `submitPrompt` (37), as specified in R5 A10. app.js: 1598 -> 1490 lines.
- `app.provide("entry", window.PadiemChatEntryModule.create(app))` registers without reading deps or wiring listeners; existing public conversation opener and regenerate handles remain in app.js. The canonical submit-time routing predicate remains inside the submit function.
- Existing state remains in app.js; the existing four live setters for conversationProduct, activeProject, activeProjectFileCount, and clawArtifactShownFor are reused. Shared accessors for clawConversationIds, clawConversationLabelsRead, and selectedAttachments are consolidated into the common context.
- `tools/verify_7809_t2_stage3.py` verifies exact bodies after explicit dependency-reference substitution (4/4), all three Android storage functions unchanged, and no change in app.js window assignments. R-06 and R-11 unchanged; no audit or rule changes.
- Focused regression: 241 passed after relocating source assertions and harness wiring; new live-state regression uses shipped context accessors and registry to verify all four restored state values and project render observation. Structure and file-size checks: 16 passed.

### #7809 T2 stage 5 (2026-11-27)

- Mode-chip click wiring moves to `chat-claw-form-module.js` via `wireModeChips()` at the original registration position. Four existing buttons, one registration site. app.js: 1490 -> 1476 lines. The original `clawLastAction` initialization stays in app.js and the module writes through the callback setter provided at the original wire position (no new deps field).
- All eight DOM refs remain shared: manual form (nav/entry), channel/action/sender (status), result area (nav/status), preview/card/empty (run). The window localechange listener remains at its original position.
- Exact normalized event body and reconstructed app.js match the base; Android storage and window assignments unchanged. Existing A5b contract verifies all four chip handlers, pressed states, selected action, focus, setter and registration order. The #2322 accessibility source assertion follows its moved aria-pressed implementation in the Claw Form module. Focused/structure/file size checks: 21 passed.
- Boot ledger: 1440 exact; 390 asynchronous registration order and DOMContentLoaded count vary on both base and head. All 18 repeated 390 runs retain the same Claw listener block (positions 149-171). No timing rule or audit changed.
