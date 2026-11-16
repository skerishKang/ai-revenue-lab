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
