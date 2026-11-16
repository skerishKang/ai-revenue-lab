# #7814 [리팩터링 v2 · T4] 서버 큰 함수 지도 (R7-0)

- 측정 기준: `origin/main` `3726bd3f7` (2026-11-16). 표의 줄 수는 `tools/chat_structure_audit.py`의 `py_functions_over_300` 정의(`ast`, `>=300`줄, 중첩 함수 포함)와 동일하다. 이슈 표(`199ea37` 기준) 대비 `create_app` 1511→1516, `oracle_mesh_read_result` 679→693, `_answer_orchestration` 468→472로 소폭 증가, 개수는 15개로 동일하다.
- 범위: `apps/padiem-chat/app/*.py`의 300줄 이상 함수 전부. `history.py`/history 영역 파일은 다른 레인(T3)이 나누고 있으므로 이 지도와 이후 PR은 건드리지 않는다.
- 구간 표기: `입력 검증 / 권한·한도 / 분기 / 외부 호출 / 기록 / 응답 조립` 6구간으로 나누어 제안한다. 줄 범위는 함수 시작~끝 중 대략 위치이며, 각 단계 PR에서 확정한다(제목의 "대략" 표기). 구간 사이 변수와 early return 수는 `ast` 실측이다.
- PC 표시: 오늘 다친 PC 경로 `#7845`(orchestration PC 의도), `#7851`(범위 밖 안내), `#7854`(답변 저장 거절 503 방지), `#7857`(결과 적재 거절 이유 로그)가 걸치는 함수는 ★로 표시한다. `#7851/#7854`는 `chat_pc_drive.py`를 고쳤으므로, 그 함수를 호출하는 큰 함수는 간접 영향으로 ★다.

## 요약

| 줄 | 파일 | 함수 | early return·raise | 글자 검사 파일 수 | 예상 PR | PC |
|---:|---|---|---:|---:|---:|:---:|
| 1,516 | `app_factory.py` | `create_app` | return 1(최종)·raise 1(내부 가드) | 31 | 2 |  |
| 1,053 | `claw_general_routes.py` | `claw_general_execute` | return 92·raise 5 | 14 | 4 | ★(간접) |
| 784 | `chat_routes.py` | `_api_chat_stream_body` | return 38·raise 3 | 14 | 3 | ★ |
| 767 | `local_cpython.py` | `build_app` | return 1·raise 9 | 14 | 3 |  |
| 693 | `oracle_mesh_read_return_routes.py` | `oracle_mesh_read_result` | return 30·raise 0 | 4 | 3 | ★ |
| 667 | `oracle_mesh_read_return_routes.py` | `_engine_pc_files_call` | return 79·raise 0 | 0(파일은 4) | 3 | ★ |
| 472 | `orchestration_routes.py` | `_answer_orchestration` | return 32·raise 0 | 9 | 2 | ★ |
| 460 | `b66_ai_chat_routes.py` | `b66_ai_chat` | return 57·raise 0 | 0 | 2 |  |
| 436 | `mcp_gateway_execution.py` | `execute_mcp_pc_tool` | return 18·raise 20 | 0 | 2 | ★ |
| 436 | `config.py` | `from_values` | return 1·raise 28 | 8 | 2 |  |
| 416 | `claw_routes.py` | `claw_manual_intake_execute` | return 33·raise 0 | 12 | 2 |  |
| 373 | `chat_routes.py` | `api_chat` | return 36·raise 1 | 14 | 2 | ★(간접) |
| 313 | `oracle_mesh_read_return_routes.py` | `_pc_write_command` | return 1·raise 0 | 파일 4 중 1 | 1 |  |
| 312 | `account_deletion.py` | `_account_delete_impl` | return 25·raise 3 | 2 | 2 |  |
| 306 | `b66_ai_conversation_routes.py` | `conversation_turn` | return 43·raise 1 | 0 | 1 |  |

- `py_functions_over_300` 15개. 파일별: `oracle_mesh_read_return_routes.py` 3개, `chat_routes.py` 2개, 나머지 1개씩.
- 열린 PR(측정일 기준 #7863·#7862·#7848·deps·B14 등) 중 같은 파일을 만지는 곳은 `#7282` 하나다(`chat_routes.py`, `orchestration_routes.py` – `_api_chat_stream_body`·`api_chat`·`_answer_orchestration`과 겹침). 그 외 열린 PR은 겹침 없음.
- T3(history) 레인은 `history.py`·`history_*`만 건드리므로 직접 겹침은 없고, `history_store`를 호출하는 큰 함수는 합병 순서만 조율하면 된다.

## 함수별

### 1. `create_app` — `apps/padiem-chat/app/app_factory.py:601-2116` (1,516줄)

- 구간(대략): 입력 검증 601-694(서명·`resolved`), 권한·한도 694-695(주입값 확인에 흡수), 분기 1204-1312(조건부 마운트 4블록), 외부 호출(상태 공장) 1339-2115, 기록 1314-2115(`app.state.*` 대입), 응답 조립 695-1200(라우트 조립)+1313-1314(앱 생성)+2116(반환). 라우트 조립 695-1200은 R7-1에서 먼저 뺀다.
- 구간 사이 변수: 40개 자리(실측 `Store` 40개). 예: `resolved`, `routes`, `app`, `_approved_memory_store`, `_auth_abuse_store`, `_b66_*_store`, `_catalog_client`, `_push_*`, `global_model_admin` 등. 라우트 조립 구간은 바깥 지역 변수를 쓰지 않으며(모듈 전역 핸들러만), 상태 초기화 구간은 `d1_binding`·`r2_binding`을 다음 구간으로 넘긴다.
- early return: 1(2116 최종 `return app`)·raise 1(1394 내부 가드). 분기는 조건부 `if`뿐이라 early return이 적다.
- 글자 검사: `app_factory.py`를 `read_text`로 읽는 31개 파일(예: `test_2824_isolated_parser_transport`, `test_3933_existing_result_reuse_adopt`, `test_4139_private_rpc_export_parity`, `test_auth_abuse`, `test_b54_claw_general_p01_routing`, `test_4471_conversation_search`). 라우트 문자열을 옮기면 파일 내 위치가 바뀌므로, 읽는 대상이 `create_app` 본문이면 새 `register_*`로 바꾸거나 라우트 표 검사로 옮긴다(약하게 만들지 않는다).
- 겹침: 열린 PR 중 같은 파일 없음. `local_cpython.build_app`이 조립 후 `create_app`을 호출하므로, 시그니처는 그대로 둔다.
- 나누기: R7-1(라우트, 1 PR) → 상태 초기화 helpers(1~2 PR). 위 두 단계 후 본체는 `Starlette(routes=...)`·미들웨어·상태 조립·반환만 남는다. 예상 2 PR(라우트 1 + 상태 1, 상태가 크면 2로 늘어남).

#### R7-1 영역 제안 (원본 순서 그대로, 인접 구간)

원본 `routes = [...]` 298 엘트(695-1200) + 조건부 4블록(1204-1312)을 아래 `register_*`로 잇댄다. 파일 내 정의 순서도 호출 순서와 같다(글자 인덱스 검사를 깨지 않기 위함). 각 등록은 인자로 받은 `routes` 목록에만 쓴다. 정적 `Mount`는 마지막에 오도록, 조건부는 정적 앞 삽입(`routes[-1:-1]`)·앞 삽입(`routes[0:0]`) 원본 코드를 그대로 유지한다.

| 호출 순서 | 함수 | 엘트 | 원본 줄(대략) | 영역 |
|---|---|---|---|---|
| 1 | `register_util_routes` | 0 | 696 | 유틸(health) |
| 2 | `register_opinion_news_routes` | 1-5 | 697-701 | 의견/새 소식 |
| 3 | `register_admin_feedback_routes` | 6-9 | 702-705 | 관리(피드백) |
| 4 | `register_site_feedback_routes` | 10-12 | 706-708 | 의견/관리(사이트 피드백) |
| 5 | `register_admin_routes` | 13-28 | 709-727 | 관리(모델·세션·역할) |
| 6 | `register_auth_voice_routes` | 29-38 | 728-738 | 인증·음성 |
| 7 | `register_auth_login_routes` | 39-59 | 739-776 | 인증(로그인) |
| 8 | `register_connector_routes` | 60-84 | 777-805 | 연결·회의(Google/GitHub/B66 drive) |
| 9 | `register_project_document_routes` | 85-113 | 806-873 | 프로젝트·문서·출력 |
| 10 | `register_chat_routes` | 114-145 | 874-923 | 대화·대화 보조(MCP·BYOK 포함) |
| 11 | `register_b66_routes` | 146-194 | 924-1033 | B66 |
| 12 | `register_web_xlsx_routes` | 195-215 | 1034-1055 | Claw 웹·XLSX·쓰기 |
| 13 | `register_claw_routes` | 216-258 | 1056-1139 | Claw |
| 14 | `register_calendar_routes` | 259-268 | 1140-1153 | 캘린더 |
| 15 | `register_pc_routes` | 269-295 | 1154-1190 | PC(페어링·파일 교환) |
| 16 | `register_static_routes` | 296-297 | 1191-1199 | 유틸·정적(리다이렉트+`Mount`) |
| 17 | `register_connector_enrollment_routes` | 조건부 | 1201-1242 | 연결(주인 전용, 정적 앞 삽입) |
| 18 | `register_oracle_mesh_routes` | 조건부 | 1243-1307 | PC·메시(정적 앞 삽입) |
| 19 | `register_shared_auth_comparison_routes` | 조건부 | 1308-1310 | 인증(시험 앞 삽입) |
| 20 | `register_shared_login_routes` | 조건부 | 1311-1312 | 인증(시험 앞 삽입) |

- 멈춤 조건: 등록 순서 변경 없이는 나눌 수 있는 구간인지가 기준이다. 지역 변수가 20개를 넘거나 상태 초기화가 뒤엉킨 영역은 R7-1에 포함하지 않고 지도의 "남김"으로 적는다. 전후 라우트 표가 달라지면 멈춘다.

### 2. `claw_general_execute` — `apps/padiem-chat/app/claw_general_routes.py:1894-2946` (1,053줄) ★(간접)

- 구간(대략): 입력 검증 1894-2050, 권한·한도 1905-1915(비로그인 거부)+본문 내 quota, 분기 2050-2600(데스크톱·PC·브라우저·목록·확인 턴), 외부 호출 2350-2850(Engine 어댑터·PC 문맥·목록 읽기), 기록 2850-2900(런·미러·계측), 응답 조립 2850-2946(SSE·JSON).
- 구간 사이 변수: 120개. 대표: `uid`, `data`, `user_text`, `adapter`, `run`, `initial_pc_capture`, `pc_owner`, `desktop_device_id`, `dispatch_args`, `outcome`, `staged_conversation_id`.
- early return: 92(대부분 `_error` early)·raise 5(2312·2328·2346·2348·2476).
- 글자 검사: `claw_general_routes.py`를 읽는 14개 중 함수 본문 근처를 보는 `test_3933_b54_first_turn_grant`, `test_b54_claw_general_p01_routing` 등.
- 겹침: 열린 PR 겹침 없음. 대화·Claw 라우트와 P01 어댑터 계약 공유.
- 나누기: 검증·권한 1 PR, 분기(PC/데스크톱) 1~2 PR, 외부 호출·기록·응답 1 PR. 예상 4 PR. 가장 위험한 축에 속한다(반환 92개).
- 1단계 완료(R7-4): 입력 검증·권한 구간(원래 1912-1977: 로그인 거부부터 첨부 충돌 생성까지, 세션·Custom·데스크톱 분기 진입 전)을 `_claw_general_intake` 75줄로 분리했다. `claw_general_execute` 1,053→994줄, `py_functions_over_300`은 12로 그대로다. 넘기는 변수 5개(`turn_started`, `data`, `user_text`, `document_context`, `attachment_conflict`)는 도우미 묶음으로 돌려받고 본체가 같은 이름으로 푼다. 조기 반환 10개는 `(오류응답, None)`으로 보존하고 본체가 `if intake_error is not None: return intake_error`로 원래 자리에서 반환한다. PC 분기(`initial_pc_capture`, `pc_owner`, `desktop_device_id`, `dispatch_args` 등)와 quota(원래 2506 이후)는 건드리지 않았다. 증거: `test_7814_claw_general_intake_table.py`(오류 18개·정상 3개 골든).

- 2/4 구간 표(1/4 완료 후, 현재 1971-2964): PC 밖은 PC 문맥 변수(`initial_pc_capture`, `pc_owner`, `desktop_device_id`, `dispatch_args`, `requested_device_id`, `pc_browser_*`, `pc_files_*`, `initial_pc_drive_query`)를 읽거나 쓰지 않는 구간이다.

  | 구간 | 줄 | 하는 일 | return | 받는 변수 | 넘기는 변수(다시 쓰는 변수) | 분류 |
  |---|---|---|---|---|---|---|
  | 세션 소유자 턴 | 1997-2003 | `handle_owner_turn`→`claw_response` | 1 | request, data, user_text, document_context | 없음 | PC 밖 |
  | Custom 직접 완성 | 2008-2047 | custom 선택·헤더·PC 의도 거부·로그인·`_claw_custom_direct` | 6 | request, data, user_text, attachment_conflict | 없음(custom·uid는 구간 안에만) | PC 밖 |
  | 데스크톱 | 2051-2067 | `_requested_local_desktop`·확인·dispatch | 3 | user_text, attachment_conflict, data | desktop_requested, desktop_op | PC |
  | 화면 보기 | 2072-2079 | 읽기 전용 화면 캡처 dispatch | 2 | user_text, attachment_conflict, data | 없음 | PC |
  | 데스크톱 통제 | 2085-2107 | 통제 op·예외 질문·확인·dispatch | 2 | user_text, attachment_conflict, data | control_requested, control_op | PC |
  | 초기 PC 캡처·데스크톱 작업 | 2113-2133 | `explicit_pc_instruction`·작업 개시 | 2 | user_text, attachment_conflict | initial_pc_capture, desktop_task_requested | PC |
  | 장치 모양·데스크톱 장치 | 2139-2142 | device_id 모양·`desktop_device_id` | 1 | data, initial_pc_capture | requested_device_id, desktop_device_id | PC |
  | 확인 턴(명령) | 2145-2149 | staged PC 명령 확인·dispatch | 1 | request, user_text, data | confirmed_command | PC |
  | 확인 턴(입력) | 2151-2158 | staged 입력 확인·dispatch | 1 | request, user_text, data | confirmed_value | PC |
  | 로컬 명령 | 2160-2174 | 명령 확인·직접/단계 dispatch | 4 | user_text, attachment_conflict, data | command_requested, command_text | PC |
  | 브라우저 분류 | 2180-2185 | `requested_pc_browser`·PC 변수 초기화 | 0 | user_text, requested_device_id | pc_browser_requested, pc_browser_device_id, initial_pc_capture, desktop_device_id | PC |
  | 목록 읽기 분류 | 2186-2191 | PC 파일 의도·장치 | 1 | pc_browser_requested, user_text, attachment_conflict, requested_device_id | pc_files_requested, pc_files_device_id | PC |
  | 자연 PC 조회 | 2195-2209 | PC 조회 명령·drive query 표식 | 3 | user_text, pc_browser_requested, attachment_conflict, requested_device_id | natural_pc_requested, natural_pc_command, initial_pc_drive_query, desktop_device_id | PC |
  | TXT 읽기 | 2211-2220 | txt 경로 dispatch | 3 | user_text, pc_files_requested, pc_browser_requested, attachment_conflict, data | txt_requested, txt_path | PC |
  | 등급·경로 | 2222-2266 | 등급·관리자·`resolve_claw_tier_model`·모델 선언 검사 | 5 | request, data | grade, requested_tier, admin_lane, product_tier, identity_tier_id, claw_route, central_route_model_id | PC 밖 |
  | 단계·대화 참조 | 2268-2277 | `_claw_stage(ROUTE)`·`_resolve_intake_session_reference` | 1 | turn_started, request, data | conversation_id | PC 밖 |
  | 어댑터·선행 읽기 | 2282-2331 | identity lane·history/session/drive 함께 읽기(`asyncio.gather`)·이력 오류 | 2+raise 1 | request, conversation_id, user_text | adapter, has_identity_lane, model_user_text, b54_session, drive_result | PC 밖 |
  | 브라우저 재검사 | 2332-2336 | history 이후 브라우저 재판정 | 0 | pc_browser_requested, user_text, requested_device_id | pc_browser_requested, pc_browser_device_id | PC |
  | 주체·Drive 정리 | 2338-2367 | b54 주체·workspace·Drive 결과 | 4+raise 2 | conversation_id, has_identity_lane, b54_session, drive_result | subject_id, authorized_workspace_id, canonical_session_id, drive_context, drive_sources | PC 밖이나 재검사 뒤라 3/4 몫 |
  | PC 문맥 | 2375-2509 | `pc_owner`·작업 공간·저장 선택·`resolve_pc_work_context` | 4 | pc_* 분류, central_route_model_id 등 | pc_owner, pc_context, pc_work_text 등 | PC |
  | quota·실행·기록·응답 | 2511-2964 | quota·live·캘린더·run·증거·dispatch·저장·SSE | 다수 | subject_id, adapter, model_user_text 등 | run, outcome, dispatch_args, staged_conversation_id, saved_conversation_id | PC/Engine/기록/응답, 3/4 몫 |
- 2단계 완료(R7-5): PC 밖 분기만 분리했다 — 세션 소유자 턴·Custom(1997-2047)을 `_claw_general_session_custom` 54줄로, 등급·경로·대화 참조·선행 읽기(2222-2331)를 `_claw_general_route_preflight` 127줄로 옮겼다. `claw_general_execute` 994→853줄, `py_functions_over_300` 12 그대로. 넘기는 변수: 세션·Custom은 request·data·user_text·document_context·attachment_conflict(5개, 돌려주는 묶음은 빈 딕셔너리), 등급·선행 읽기는 request·data·user_text·turn_started(4개)를 받고 grade·requested_tier·admin_lane·product_tier·identity_tier_id·claw_route·central_route_model_id·conversation_id·adapter·has_identity_lane·model_user_text·b54_session·drive_result(13개)를 다시 쓴다. 브라우저·목록·확인 턴 등 PC 구간(2051-2220과 2332 이후)은 PC 문맥 변수를 읽거나 써서 이번에 건드리지 않았고 3/4 몫으로 남겼다. 증거: `test_7814_claw_general_branches_table.py`(15개 골든). 글자 검사 1개(`test_b54_claw_general_p01_routing`)는 옮긴 문자열을 새 함수 블록까지 함께 보도록 고쳤다.

### 3. `_api_chat_stream_body` — `apps/padiem-chat/app/chat_routes.py:682-1465` (784줄) ★

- 구간(대략): 입력 검증 682-800, 권한·한도 800-900, 분기 900-1200(스트림·비스트림·PC·연결자), 외부 호출 1200-1400(모델·PC 드라이브·그라운딩), 기록 1400-1430(대화 저장), 응답 조립 1430-1465(SSE).
- 구간 사이 변수: 78개. 대표: `conversation_id`, `user_id`, `model`, `messages`, `attachments`, `existing_conversation`, `execute_chat_pc_drive_lane`, `pc_scope_notice`, `answer`.
- early return: 38·raise 3(954·1136·1138).
- 글자 검사: `chat_routes.py`를 읽는 14개(`test_5247_chat_claw_error_contract`, `test_7297_claw_server_contract` 등).
- 겹침: 열린 `#7282`와 파일 겹침(캘린더 경로). PC 오늘 경로의 호출부(1258·1311 줄 부근) — `chat_pc_drive` 계약 변경 시 함께 본다.
- 나누기: 검증·권한 1, 분기(스트림/PC) 1, 외부·기록·응답 1. 예상 3 PR.

### 4. `build_app` — `apps/padiem-chat/app/local_cpython.py:726-1123` (398줄)

원본 767줄(251-1017). T4는 세 단계로 나누며 1/3·2/3·3/3a가 끝났다.

- 1/3 `_compose_local_settings_and_bindings`(251-316): 진입 플래그·설정 검증 + SQLite/disk-R2.
- 2/3 `_compose_local_service_bindings`(319-452): 저장소·서비스 바인딩(반환 8값).
- 3/3a `_install_local_host_state`(455-723, 269줄): startup/shutdown 훅, WAL·감시자, auth 캐시·로컬 검증, 메일 채널, council 라우트, 기기 저장소·큐, broker 디렉터리. 호출 904에서 `app`을 받아 같은 순서로 대입한다.

| 순서 | 구간 | 리팩터 후 줄 | 내용 | 상태 |
|---|---|---|---|---|
| 1 | 설정 읽기·검증 + SQLite/disk-R2 | helper 251-316 / 호출 326 | 진입 플래그, 데이터 폴더·세션 비밀값, `Settings.from_env()` 검증, sqlite 연결·마이그레이션, `SqliteD1`, `ThreadedLocalDiskR2` | 완료 |
| 2 | 저장소·서비스 바인딩 | helper 319-452 / 호출 464-473 | `_optional_pair` 4종, github_oauth 포트, identity authority, cache-generation store, shadow store, pdf renderer | 완료 |
| 3 | `create_app` 호출 | 803-842 | 같은 시그니처·같은 인자 순서 | 본체 유지 |
| 4 | 상태 조립 — 훅·캐시·메일·council·기기 | helper 455-723 / 호출 904-915 | 위 3/3a 목록, 대입 순서 그대로 | 완료(3/3a) |
| 5 | 상태 조립 — B14 전송·게이트·오케스트레이션 | 917-1120 | `if settings.runtime_mode == "b14":` 블록, edge proof, connector gateway, orchestration, apps ai ingress | 3/3b 몫 |
| 6 | 마무리 | 1122-1123 | write freeze 래핑과 반환 | 본체 유지 |

- 본체 398줄, `_install_local_host_state` 269줄. 본체가 아직 300줄을 넘으므로 `py_functions_over_300`은 10 그대로다(3/3b에서 B14·게이트 구간을 덜어내면 9).
- 골든: `tests/test_7814_local_build_app_table.py` — 1/3 거절 4경로·표면, 2/3 바인딩 쌍, 3/3a `app.state` 대입 순서(146회·이름 142개, base·identity_on 두 입력).

### 5. `oracle_mesh_read_result` — `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:3239-3931` (693줄) ★

- 구간(대략): 입력 검증 3239-3350, 권한·한도 3350-3500, 분기 3500-3700(데스크톱·PC·브라우저·파일), 외부 호출 3700-3850(엔진·메시 소스), 기록 3850-3900(히스토리·감사), 응답 조립 3900-3931.
- 구간 사이 변수: 55개. 대표: `conversation_id`, `messages`, `history_store`, `mesh_source`, `command_text`, `dispatch`, `finished`, `appended`.
- early return: 30·raise 0.
- 글자 검사: `oracle_mesh_read_return_routes.py`를 읽는 4개(`test_261109_pc_result_host_visible`, `test_5479_longpoll_bounded_wait` 등).
- 겹침: 열린 PR 없음. 오늘 `#7857`이 같은 파일의 결과 적재부를 다침(로깅 추가) — 후속 나눌 때 로깅 자리를 그대로 본다.
- 나누기: 검증·권한 1, 분기·외부 1, 기록·응답 1. 예상 3 PR. 파일이 6,379줄·최상위 100개이므로, 함수별 PR보다 파일 단계 분할과 함께 계획하는 편이 좋다.

### 6. `_engine_pc_files_call` — `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:5315-5981` (667줄) ★

- 구간(대략): 입력 검증 5315-5430, 권한·한도 5430-5550, 분기 5550-5770(읽기/쓰기·범위·확인), 외부 호출 5770-5900(PC 파일·엔진), 기록 5900-5950(히스토리), 응답 조립 5950-5981.
- 구간 사이 변수: 94개. 대표: `device_id`, `destination_path`, `content_b64`, `dispatch`, `bound`, `command`, `history_store`.
- early return: 79·raise 0(가장 잦은 early return 그룹).
- 글자 검사: 파일 4개 중 함수명을 글자로 직접 보는 시험은 0개(행위는 `test_261104_pc_files_early_return`, `test_7065_pc_edit_tool` 등의 호출 시험으로 본다).
- 겹침: 열린 PR 없음. `#7857`의 로깅이 인접.
- 나누기: 검증·권한 1, 분기·외부 1, 기록·응답 1. 예상 3 PR.

### 7. `_answer_orchestration` — `apps/padiem-chat/app/orchestration_routes.py:356-827` (472줄) ★

- 구간(대략): 입력 검증 356-440, 권한·한도 440-490, 분기 490-650(오케스트레이션 의사결정), 외부 호출 650-780(모델·브리지·PC 의도), 기록 780-810, 응답 조립 810-827.
- 구간 사이 변수: 65개. 대표: `conversation_id`, `decision`, `bridge`, `confirmed`, `explicit_intent`, `byok_model`, `grounded_evidence`.
- early return: 32·raise 0.
- 글자 검사: `orchestration_routes.py`를 읽는 9개 중 `test_orchestration_timing_261103`, `test_7841_pc_task_intent`, `test_7841_pc_tools_timing` 등.
- 겹침: 열린 `#7282`와 파일 겹침. 오늘 `#7845`가 이 함수(PC 의도 부스팅)를 직접 다침 — 같은 파일을 만지는 PR은 합병 순서를 조율한다.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.
- 구간 표(B4-1 선행, 2026-11-17 기준):
  | 구간 | 줄 범위 | 반환 | 받는 변수 | 넘기는 변수 | 다시 쓰는 변수 |
  |---|---|---:|---|---|---|
  | 입력·본인 확인 | 725-771 (`_account_delete_identity`) | 10 | request, bookai_subject_id | db, user_id, row, email | db, user_id, row, email |
  | 권한(관리자 차단) | 위 구간에 포함 | 3 | db, user_id, email | — | — |
  | 삭제 대상 수집 | 780-846 | 4 | db, user_id, row | cleanup_targets, subjects, links | subject_id, marker_subject |
  | 삭제 실행·기록 | 849-1006 | 5 | db, cleanup_targets, subjects | deleted_subjects | shared_complete_pending |
  | 응답 | 1008-1036 | 1 | cleanup, shared_complete_pending | body | — |
- 완료(B4-1): 본체 314→278줄. 앞 구간(입력·본인 확인+관리자 차단)을 `_account_delete_identity`(47줄)로 떼어 냈다. 도우미는 `(응답 | None, 값 묶음)`을 돌려주고 본체가 원래 자리에서 `if resp is not None: return resp`로 같은 응답을 반환한다. 삭제 실행 순서·트랜잭션 경계·외부 호출 순서는 그대로다. 증거: `test_7814_account_delete_table.py`(거절 10경로 + 통과 1경로, 거절 경로 삭제 0건).

- 구간 표(최신 main, 883-1298):
  | 구간 | 줄 | 하는 일 | return | 받는 변수 | 넘기는 변수(다시 쓰는 변수) |
  |---|---|---|---|---|---|
  | 입력 검증 | 887-926 | 로그인 거부·content-type·본문·JSON·객체·원문·채널·작업 | 9 | request | data, content_clean, channel, action |
  | 권한·한도(등급) | 931-974 | 작업 길이·발신자 힌트·등급·관리자·등급 거부·중앙 경로 | 5 | request, data, content_clean, action | sender_hint, grade, product_tier, identity_tier_id, claw_route |
  | intake 조립·세션 참조 | 976-1006 | `ManualIntakeRequest`·`ManualIntakeRouter`·세션 참조 | 3 | request, data, channel, action, content_clean, sender_hint | session_conversation_id(intake_req는 구간 안에만) |
  | 산출물 권한 | 1010-1030 | 견적·주문 draft의 tenant·owner·스토어 | 2 | request, action | artifact_tenant_id, artifact_owner_id, artifact_store |
  | 어댑터·주체·quota | 1036-1086 | adapter 읽기·B54 주체·usage gate·adapter 없음 | 4 | request | adapter, subject_id |
  | Engine 호출 | 1088-1129 | task·run·`adapter.execute`·예약 해제 | 2 | action, content_clean, adapter, product_tier, subject_id, claw_route, identity_tier_id | run, outcome |
  | 결과 투영 | 1136-1217 | waiting_approval·미완료 거부 | 2 | outcome | 없음 |
  | 기록·응답 조립 | 1219-1298 | 제목·산출물 설명·결과·이력 기록·200 응답 | 2 | channel, action, sender_hint, artifact_*, session_conversation_id, run, outcome | 없음 |
  PC·메시·데스크톱을 부르는 줄은 이 함수 안에 없다(Engine `adapter.execute`만 있다).
- 완료(R7-6): 입력 검증·등급·경로(887-974)를 `_claw_manual_intake_validate` 101줄로, intake 조립·세션·산출물·어댑터·quota(976-1086)를 `_claw_manual_intake_prepare` 121줄로 분리했다. 본체 416→239줄, `py_functions_over_300` 12→11. 다시 쓰는 변수: validate는 data·content_clean·channel·action·sender_hint·grade·product_tier·identity_tier_id·claw_route(9개), prepare는 session_conversation_id·artifact_tenant_id·artifact_owner_id·artifact_store·adapter·subject_id(6개). PC·메시·데스크톱 줄은 없어 옮기지 않았다. 증거: `test_7814_claw_manual_intake_table.py`(25개 골든). 금지 경로 시험: `test_usage_gate_is_applied_before_p01_adapter_construction`와 `test_execute_route_has_no_body_driven_refund_authority`는 도우미까지 함께 보도록 넓혔다.

### 8. `b66_ai_chat` — `apps/padiem-chat/app/b66_ai_chat_routes.py:278-737` (460줄)

- 구간(대략): 입력 검증 278-350, 권한·한도 350-420, 분기 420-600(관점·모델·등급), 외부 호출 600-690(가드 클라이언트), 기록 690-720, 응답 조립 720-737.
- 구간 사이 변수: 57개. 대표: `conversation_id`, `declared_model_id`, `expected_model`, `guarded_client`, `attempt_store`, `decision`, `answer`.
- early return: 57 제자리 크기(거부·재시도 분기). raise 0.
- 글자 검사: `b66_ai_chat_routes.py`를 직접 읽는 시험 0개(호출 시험 위주).
- 겹침: 열린 PR 없음.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.

### 9. `execute_mcp_pc_tool` — `apps/padiem-chat/app/mcp_gateway_execution.py:238-673` (436줄) ★

- 구간(대략): 입력 검증 238-320, 권한·한도 320-420(승인·장치), 분기 420-520(도구별 계획), 외부 호출 520-610(PC 실행·브라우저), 기록 610-650(대화 기록), 응답 조립 650-673.
- 구간 사이 변수: 61개. 대표: `tool_name`, `arguments`, `approval_id`, `device_id`, `chosen_device`, `chat_pc_plan_for_tool`, `bridge`, `browser`, `conversation_id`.
- early return: 18·raise 20(raise 265·268·272·293·348·355·361·365 등 — raise가 많은 그룹).
- 글자 검사: 파일 직접 읽는 시험 0개(호출 시험 `test_7065_pc_edit_tool`, `test_mcp_multi_device_261104` 등).
- 겹침: 열린 PR 없음. 오늘 PC(`#7851/#7854`)의 `chat_pc_drive`를 부르므로 간접 ★.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.

### 10. `from_values` — `apps/padiem-chat/app/config.py:322-757` (436줄)

- 구간(대략): 입력 검증 322-430, 권한·한도(설정 한도) 430-560, 분기 560-660(모드·제공자), 외부 호출 — 없음(순수 파싱, 키 정규화), 기록 — 없음, 응답 조립 660-757(`Settings` 생성·반환). 조립 함수라 6구간 중 외부 호출/기록은 비어 있다.
- 구간 사이 변수: 53개 자리(입력 키 60여 개)·111개 자리(실측 Store 총계). 대표: `b14_base_url`, `auth_mode`, `client_id`, `normalized`, `extra_base_urls`, `max_age`.
- early return: 1(637·내부 정규화 반환)·raise 28(394·405·416·424·432·440·459·464 등 검증 오류) — raise 중심.
- 글자 검사: `config.py`를 읽는 8개(`test_4139_private_rpc_export_parity`, `test_staging_config_6305` 등).
- 겹침: 열린 PR 없음. 합성 함수라 호출부(`build_app`, `create_app`)가 많다.
- 나누기: 키 그룹별 validators 2 PR(검증/한도, 분기/조립). 예상 2 PR. 가장 먼저 나눌 후보(순수·raise 중심·외부 의존 없음).
- 완료(R7-3): `from_values` 436→242줄, 단계 함수 5개(모두 300줄 이하)로 분리 — `_values_runtime_flags` 58줄(실행 모드·운영 플래그), `_values_b14_and_timeouts` 57줄(B14·타임아웃), `_values_web_search` 34줄(웹 검색), `_values_auth_session` 70줄(인증·세션), `_values_limits_document` 71줄(한도·문서 변환). 검증·조립 순서와 생성자 안 인라인 검증을 그대로 두어 오류 우선순위를 보존했다. 증거: `test_7814_config_from_values_table.py`(대표 입력의 설정 필드·값과 오류 메시지, `from_env` 환경 변수 접근 순서 골든).

### 11. `claw_manual_intake_execute` — `apps/padiem-chat/app/claw_routes.py:883-1298` (416줄)

- 구간(대략): 입력 검증 883-960, 권한·한도 960-1010, 분기 1010-1150(수 intake·산출물·등급), 외부 호출 1150-1240(어댑터·스토어), 기록 1240-1270, 응답 조립 1270-1298.
- 구간 사이 변수: 43개. 대표: `data`, `action`, `adapter`, `intake_req`, `artifact_*`, `grade`, `denial`, `outcome`.
- early return: 33·raise 0.
- 글자 검사: `claw_routes.py`를 읽는 12개(`test_claw_execution`, `test_bounded_request_body` 등).
- 겹침: 열린 PR 없음.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.

### 12. `api_chat` — `apps/padiem-chat/app/chat_routes.py:1474-1846` (373줄) ★(간접)

- 구간(대략): 입력 검증 1474-1550, 권한·한도 1550-1600, 분기 1600-1700(비스트림·연결자·그라운딩), 외부 호출 1700-1800(모델·문서·드라이브), 기록 1800-1820, 응답 조립 1820-1846.
- 구간 사이 변수: 60개. 대표: `body`, `conversation_id`, `document_context`, `drive_context`, `custom_result`, `google_connector_turn`, `grounded`.
- early return: 36·raise 1(1790).
- 글자 검사: `chat_routes.py`를 읽는 14개 + `api_chat`을 직접 보는 8개(`test_7297_parity_gates`, `test_bounded_request_body` 등).
- 겹침: 열린 `#7282`와 파일 겹침. `_api_chat_stream_body`와 한 파일이므로 함께 계획한다.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.

### 13. `_pc_write_command` — `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:4349-4661` (313줄)

- 구간(대략): 입력 검증 4349-4420, 권한·한도 — 없음(호출부에서 검증), 분기 4420-4550(덮어쓰기·추가·검증), 외부 호출 4550-4640(파일·백업), 기록 4640-4655, 응답 조립 4655-4661(반환).
- 구간 사이 변수: 6개 자리 — 가장 작다(`append_probe`, `backup_step`, `body`, `target_missing`). 인자로만 동작하므로 분리 난도가 낮다.
- early return: 1(4661 최종)·raise 0.
- 글자 검사: `test_7065_pc_edit_tool` 1개.
- 겹침: 열린 PR 없음.
- 나누기: 1 PR(검증, 분기·외부·기록·응답). 가장 먼저 처리 가능.
- 완료(R7-2): `_pc_write_command` 313→63줄, 단계 함수 5개(모두 300줄 이하)로 분리 — `_pc_write_backup_fragments` 14줄(외부 호출: 백업·대상 없음 조각), `_pc_write_input_statements` 40줄(입력 검증: 초기 문장·관찰 대상), `_pc_write_scope_guard` 37줄(권한·한도: 허용 범위 밖 바로가기 경로 거절), `_pc_write_operation_body` 131줄(분기: 덮어쓰기·추가·편집·폴더·이동·삭제), `_pc_write_record_statements` 69줄(기록·응답: 거절 문장·검증·계정 줄). 본체는 단계 호출만 순서대로 이어 붙인다. 증거: `test_7814_pc_write_command_table.py`(대표 8개 입력의 명령 해시·이유 코드·단계 순서 골든).

### 14. `_account_delete_impl` — `apps/padiem-chat/app/account_deletion.py:774-1051` (278줄)

- 구간(대략): 입력 검증 725-785, 권한·한도 785-850, 분기 850-950(연결·주제·마지막 공동 삭제로 분기), 외부 호출 950-1010(스토어·정리), 기록 1010-1030, 응답 조립 1030-1036.
- 구간 사이 변수: 39개. 대표: `request`, `delete_all_services`, `preparation`, `cleanup_targets`, `deleted_subjects`, `auth_operation_id`.
- early return: 25·raise 3(857·872·963).
- 글자 검사: `account_deletion.py`를 읽는 2개(`test_7084_session_cache_window_261108`, `test_7388_conversation_soft_delete`).
- 겹침: 열린 PR 없음.
- 나누기: 검증·권한 1, 분기·외부·기록·응답 1. 예상 2 PR.

### 15. `conversation_turn` — `apps/padiem-chat/app/b66_ai_conversation_routes.py:184-489` (306줄)

- 구간(대략): 입력 검증 184-245, 권한·한도 245-290, 분기 290-400(관점·등급·초안), 외부 호출 400-470(가드 클라이언트), 기록 470-485, 응답 조립 485-489.
- 구간 사이 변수: 45개. 대표: `data`, `declared_model_id`, `expected_model`, `guarded_client`, `draft`, `loaded`, `message`.
- early return: 43(가장 촘촘한 early)·raise 1(454). 300줄이면서 early가 많으므로, 뺀 뒤 300줄 기준은 쉽게 만족한다.
- 글자 검사: 파일 직접 읽는 시험 0개.
- 겹침: 열린 PR 없음. `b66_ai_chat`과 함께 B66 묶음으로 계획한다.
- 나누기: 1 PR. `b66_ai_chat`과 합쳐도 된다.

## 나누는 순서 제안

위험이 낮은 것부터, PC 오늘 경로와 열린 `#7282`를 한 번에 넘지 않게 배치한다.

1. `_pc_write_command` (1) — 변수 6개·early 1. 다른 함수와 연결이 가장 얇다.
2. `conversation_turn` (1) — 파일 글자 검사 0. B66 묶음 시작.
3. `from_values` (2) — 순수 파싱·raise 중심·외부 없음. 검증/분기 조립으로 나뉜다.
4. `create_app` 상태 초기화 (1~2) — R7-1 라우트 후, 상태 조립을 단계 helpers로. 시그니처 유지.
5. `claw_manual_intake_execute` (2) — `claw_general_execute`보다 작다.
6. `b66_ai_chat` (2) — #15와 독립 PR.
7. `_account_delete_impl` (2) — 권한·외부 호출 단계가 뚜렷하다.
8. `execute_mcp_pc_tool` (2) — raise가 많으므로 raise 자리는 이동하지 않는다.
9. `api_chat` (2) — `#7282` 합병 후 착수.
10. `_answer_orchestration` (2) — `#7282`·`#7845` 합병 후 착수.
11. `_api_chat_stream_body` (3) — `api_chat`과 한 파일, PC 호출 포함.
12. `claw_general_execute` (4) — 크기 1,053·return 92. 검증, 분기, 외부·기록·응답으로 나눈 뒤에도 300줄을 피하려면 4개가 필요하다.
13. `_engine_pc_files_call` (3) — return 79.
14. `oracle_mesh_read_result` (3) — 파일 단계 분할과 함께.
15. `build_app` (3) — `create_app`과 맞물리므로 마지막.

- R7-1은 위 순서 중 `create_app` 라우트 부분만 수행한다(라우트 표·미들웨어 순서 전후 동일 시험 포함). 상태 초기화는 위 4번째다.
- 한 PR은 한 카드(함수 1개 또는 그 안의 1 구간)이므로, 함수별 예상 PR 수는 위와 같다.
