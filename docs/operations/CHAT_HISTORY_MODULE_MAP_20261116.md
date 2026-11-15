# #7790 R6 — Chat `history.py` 기능 구역 지도 (0단계)

기준: latest `origin/main` (`f94ffd2dc`), `apps/padiem-chat/app/history.py` **4,607줄**.
목적: 동작·응답 형식·DB 쿼리 결과를 바꾸지 않고 위치만 옮기는 첫 분리를 위한 지도다.
본 문서는 코드 이동을 포함하지 않는다. 이동 원칙은 "위치만 옮김, 조건·쿼리 개선 금지, `history.py`는 기존 공개 이름을 다시 내보내는 진입점으로 남김, 다른 모듈의 import 경로·함수 이름 그대로"이다.

## 1. 기능 구역

`history.py`는 아래 17개 구역으로 나눈다. 줄 번호는 기준 커밋 실측이다.

| 구역 | 줄 | 내용 | 대표 이름 |
|---|---|---|---|
| A. 상수·범위 | 21–49, 90–142 | 메시지·검색·프로젝트·실행·메시 상한, SQL 조각 | `MAX_HISTORY_MESSAGE_CHARS`, `PRODUCT_SCOPE_*`, `ORACLE_MESH_*`, `MAX_MESH_*` |
| B. 프로젝트 커서 | 47–89 | 페이지 커서 코덱 | `PROJECT_CURSOR_MAX_CHARS`, `ProjectCursorError`, `encode_project_cursor`, `decode_project_cursor` |
| C. 멀티 커맨드·요약 합병 | 91–96, 145–172 | 한 실행의 다중 PC 호출 표시와 요약 합병 | `MULTI_COMMAND_RUN_ACTIONS`, `is_multi_command_action`, `_merge_run_result_summaries` |
| D. Oracle 메시 원본 상한 | 174–216 | 읽기/명령 원본의 바이트 상한 판단 | `ORACLE_MESH_ORIGINAL_MAX_BYTES`, `_oracle_mesh_original_max_bytes` |
| E. 제품·PC 범위 안내 | 229–320 | 제품 범위 검증, PC 범위 마커·안내문 | `PRODUCT_SCOPE_CHAT/B66`, `_require_product_scope`, `PC_SCOPE_NOTICE_LABELS`, `strip_pc_scope_marker`, `pc_scope_notice` |
| F. 예외·프로필·협약 | 321–428 | 오류 계급, 프로필, `HistoryStore` 협약 | `HistoryError` 등 5종, `UserProfile`, `PasswordCredential`, `ProjectProfile`, `HistoryStore` |
| G. 검색 보조 | 429–452 | 질의 정규화·발췌 | `_normalize_search_query`, `_search_snippet` |
| H. 날짜·레인·확인 만료 보조 | 454–553 | ISO 변환, 대기 시간, 확인 카드 만료 규칙 | `_iso`, `_lane_seconds`, `_lane_count_age`, `_lane_node`, `_now_iso`, `expire_stale_confirmation_cards_for_all_owners` |
| I. ID·검증·프로젝트 문맥 | 554–734 | ID 생성, 식별자 검증, 프로젝트 문맥 문장 | `_user_id`, `_chat_id`, `general_answer_message_id`, `validate_conversation_id` 등, `build_project_context` |
| J. 미리보기·제목 | 735–779 | bounded 미리보기, 제목 추출, 미리보기 판정 | `HISTORY_PREVIEW_SUFFIX`, `_bounded_text`, `_title_from_user_text`, `_is_bounded_preview` |
| K. 행 변환 | 780–953 | D1 행→dict, 공개 투영, 검증 태그 | `_changed_rows`, `_batch_returned_row`, `_row_to_dict`, `_rows_from_result`, `_run_history_public`, `VerifiedDispatch`, `_tagged` |
| L. 저장 공통·풀 원문 | 954–1310 | `__init__`/`_dispatch`, R2 풀 원문, `_first/_run/_all` | `_put_full_message`, `_read_full_message`, `get_conversation_model_context`, `_first`, `_run`, `_all` |
| M. 계정 저장 | 1312–1612 | 사용자·비밀번호 자격 저장 | `upsert_google_user`, `register_password_user`, `find_password_credential` 등 |
| N. 대화·프로젝트 저장·조회·검색 | 1614–1996 | 대화 목록·검색·상세·변경·삭제, 프로젝트 목록·페이징, 첫 교환 저장 | `list_conversations`, `search_conversations`, `get_conversation`, `append_exchange`, `list_projects_page` |
| O. 실행 기록 | 1998–3432 | Claw·채팅 스트림·소유자 산출물·명령 결과 기록 | `record_claw_run`, `begin_chat_stream_turn`, `get_claw_run_result`, `append_command_result`, `append_local_task_result` 등 |
| P. Oracle 메시 배포 원자 | 3434–4335 | 배포 생성·청구·소비·원본 보관·열림 상태 | `create_oracle_mesh_dispatch`, `claim_oracle_mesh_dispatch`, `oracle_mesh_lane_status`, `store_oracle_mesh_command_result` 등 |
| Q. 승인 인계 | 4337–4606 | 인계 기록·불러·청구·확정·소비 | `record_claw_approval_handoff`, `load_claw_approval_handoff`, `claim_claw_approval_handoff` 등 |

문자열 검사 대상인 구역은 §4대로 기록한다.

## 2. 구역 간 호출 관계

- `F` 예외는 모든 구역이 raise/판정에 쓴다. 연구 관점에서는 가장 얽힌 구역이다.
- `K` 행 변환은 `L–Q` 모든 저장 방법이 쓴다.
- `J` 미리보기는 `N`의 `append_exchange`와 `O`의 결과 기록이 쓴다. `L`의 풀 원문 읽기는 `J` 판정으로 미리보기와 원문을 구분한다.
- `I` 검증·ID는 `N/O` 전체가 쓴다. `E` 범위 검증은 `N`의 대화·검색·상세 진입점이 쓴다.
- `G` 검색 보조는 `N`의 `search_conversations`만 쓴다.
- `B` 커서는 `N`의 `list_projects_page`만 쓰며, 외부 3파일이 같은 커서를 목록 페이징에 재사용한다.
- `H`의 `_lane_*`는 `P`의 `oracle_mesh_lane_status`만 쓴다. `_iso/_now_iso`는 전 구역이 쓴다.
- `C`의 `_merge_run_result_summaries`는 `O`의 `append_command_result` 한 곳에서만 쓰인다. `is_multi_command_action`은 내부 쓰기보다 외부 판정에 더 많이 쓰인다.
- `D` 상한 판단은 `P`의 원본 보관 경로에서 쓰이며, 읽기/명령을 구분한다.
- `L`의 공통 실행은 `M–Q` 전 구역이 쓴다.

웹 검색 판단 라인과 겹침 확인: `history.py` 본문에 `web_search`, `answered_with_evidence` 문자열은 없다(검색 대상 `create_web_xlsx_p01_run`은 문자 그대로 이름에 `web`이 있을 뿐, 웹 검색 판단 분기 아니다). 답변 경로 파일(`#7784` 웹 검색 판단·`#7785` 렌더러)과 `app.js`(`#7776`)에서는 `history.py`를 건드리지 않았고, 본 지도에서도 해당 경로는 대상에서 제외한다.

## 3. 외부에서 import하는 이름 목록 (grep 근거)

`grep`은 `apps/padiem-chat/app/*.py`와 `tests/*.py`에서 `from .history import …` / `from app.history import …` 를 수집했다. app 파일 80여 곳, 시험 파일 150여 곳이 걷힌다. 빈도 높은 이름은 다음과 같다.

- 가장 많이 외부 사용: `D1HistoryStore`(시험 다수), `PRODUCT_SCOPE_CHAT`(app·시험 다수), `HistoryStore`, `HistoryError`, `_row_to_dict`, `_rows_from_result`, `validate_conversation_id`, `UserProfile`
- 구역별 외부 사용 수(서로 다른 파일 수, 중복 제거 기준, 기준 커밋):
  - B 커서: 3개 app 파일(`approved_memory`, `saved_outputs`, `project_routes`) + 2개 시험(`test_projects_cursor_page_261102`, `test_list_cursor_outputs_memories_261102`)
  - C 중 `is_multi_command_action`: 2개 app + 3개 시험 / `_merge_run_result_summaries`: 0개
  - D: 0개 app + 2개 시험
  - G: 0개 app + 1개 시험
  - H 중 `_lane_*`: 0개 / `_iso`: 1개 app (`password_recovery`)
  - E: 10개 이상 app(범위 상수·`validate_*` 인접)
  - I: 25개 이상 app(`validate_conversation_id` 단독으로 20여 파일, `validate_project_id` 포함 시 더 증가)
  - J: 5개 이상 app, 5개 이상 시험
  - K: 25개 이상 app(`_row_to_dict` 단독 20여 파일)
  - F: 20개 이상 app·시험
- 외부 사용이 0인 내부 전용 이름: `_lane_seconds`, `_lane_count_age`, `_lane_node`, `_merge_run_result_summaries`
- 외부 1파일 이하인 이름: `_normalize_search_query`, `_search_snippet`(시험 1파일)
- 외부 3파일 이하인 이름: B 커서 4종, `_oracle_mesh_original_max_bytes`(시험 2파일)

재수출 원칙: 이동한 이름은 `history.py`에서 그대로 다시 내보낸다. 기존 `from .history import X`와 `from app.history import X` 경로는 변경하지 않는다.

## 4. 구역별로 `history.py`를 문자열 검사하는 시험 목록

- 전체 파일 문자열 검사: `test_2505_chat_claw_conversation_continuity.py::test_the_server_still_keeps_one_scoped_record_for_both_lanes`는 `PRODUCT_SCOPE_*` 3종을 `history.py` 본문에서 찾는다. E 구역 이동 시 깨지므로 E는 첫 구역 후보에서 제외한다.
- 함수 본문 추출 검사: `test_7459_pc_scope_marker_hidden.py`는 `history.py`에서 `strip_pc_scope_marker` 본문을 꺼내 직접 실행한다. E 구역 이동 시 깨지므로 제외한다.
- 파일 위치 검사: `tests/conftest.py`의 파일 이름 목록에 `test_auth_history.py`가 있다(파일 이름 자명, 본문 검사 아님).
- 시험 직접 호출(문자열 아님): `G`는 `test_4471_conversation_search.py`, `B`는 커서 페이징 시험 2종, `D`는 `test_4139_mesh_original.py` 등에서 함수·값을 직접 부른다.
- 그 외 `history.py` 경로를 읽는 시험은 위치·구성 검증이며 본문 문자열 검사는 아니다.

## 5. 첫 구역 선정과 이유, 이동 후 줄 수 규칙

선정: **B. 프로젝트 커서** (`PROJECT_CURSOR_MAX_CHARS`, `ProjectCursorError`, `encode_project_cursor`, `decode_project_cursor`).

이유:

- 표준 라이브러리만으로 단독 실행이 가능하고, DB·네트워크·모델 호출·외부 상수·`HistoryError`에 의존하지 않는다.
- 내부 호출처가 `list_projects_page` 1곳으로 좁고, 외부 재사용 3파일은 모두 `history.py` 재수출 경로를 거치므로 경로 변경 없이 유지된다.
- 문자열로 본문을 찾는 시험 2종(E 구역 검사)과 분리되어 있어 기존 시험이 깨지지 않는다.
- `_lane_*`(외부 0개)는 `HistoryError`에 의존해 순환 import가 생기고, `_merge_run_result_summaries`(외부 0개)는 단독 함수로 구역 단위가 되기 어려워 1차 후보에서 제외했다.

줄 수 규칙(각 시점 실제 줄 수 + 100, `splitlines()` 기준):

- 본 PR 전: 4,607줄 → 상한 4,707줄. 이동 후에는 실측 + 100으로 내리고 상향 금지다.
- 새 모듈 목표: 500줄 이하. 1,000줄을 넘으면 파일 맨 위에 이유와 예외 목록을 적는다. (이번 모듈은 수십 줄 규모로 500줄 목표를 만족한다.)
- 기존 `test_r5_file_size_guard_7216.py` 방식: `ROOT / "apps" / "padiem-chat" / "app" / "history.py"` 와 새 모듈 경로를 `splitlines()`로 세어 상한을 단언한다. 상한 상향 금지·예외 없는 1,000줄 초과 실패·500줄 초과 경고를 따른다.

## 6. 이동 결과 (1단계·2단계)

1단계(머지 #7796): B 프로젝트 커서를 `history_project_cursor.py`(55줄)로 이동. `history.py` 4,607줄 → 4,570줄, 상한 4,707 → 4,670줄.

2단계(본 PR): 다음 2개 구역을 이동했다.

- G 검색 보조 6개 이름(`MAX_CONVERSATION_SEARCH_QUERY_CHARS/RESULTS/SCAN_ROWS/SNIPPET_CHARS`, `_normalize_search_query`, `_search_snippet`) → `history_search.py`(40줄). 외부 app 사용은 `conversation_routes` 1파일이며 `HistoryError`·DB에 의존하지 않는다.
- C의 요약 합병 2개 이름(`MAX_RUN_RESULT_SUMMARY_CHARS`, `_merge_run_result_summaries`) → `history_run_summary.py`(25줄). `_merge_run_result_summaries`는 외부 0파일이며 상수만 3개 app 파일이 쓴다. `is_multi_command_action`과 `MULTI_COMMAND_RUN_ACTIONS`은 이번에 남긴다.

`_lane_*`(외부 0개)는 `HistoryError`에 의존해 이번에 남긴다. `HistoryError` 모듈 분리와 같은 단계에서 함께 옮기는 편이 순환 import 없이 분리할 수 있어 후속 단계에서 처리한다.

`history.py` 4,570줄 → 4,532줄, 상한 4,670 → 4,632줄. 두 새 모듈은 모두 500줄 목표를 만족한다. 겹침 주의 파일(`drive_case_folder_*`, pdfmd 관련, `apps/padiem-auth`·`auth_routes.py`·`chat-auth-module.js`, `app.js`)은 건드리지 않았다.
