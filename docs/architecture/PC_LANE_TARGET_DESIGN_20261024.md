# PC 레인 목표 설계 — 2026-10-24

CENTRAL CTO 작성, Owner 승인 범위. 추적: #5573. 2차 구현: #5689.
이 문서는 목표 계약이며, 병합·배포·운영 검증 완료를 뜻하지 않습니다. 실제 상태와 증빙은 해당 PR에 기록합니다.

## 1. 요구 (#5573, Owner)

1. 키워드 목록이 아니라 문장·대화 맥락으로 AI가 도구를 고른다.
2. 모든 일반 대화에 별도 분류 호출을 붙이지 않는다.
3. 일반 스트리밍·BYOK·tier/alias·선택 모델을 보존한다.
4. 권한(소유자·워크스페이스·기기·경로·크기·멱등성)은 서버가 검증한다.
5. 목록만 요청한 턴은 파일 내용을 읽지 않는다.
6. Native(Broker) 등록은 Mesh 파일 작업의 선행조건이 아니다.

## 2. 핵심 원칙 — 실행 상한

**실행 상한(ceiling) = 사용자 요청 범위 ∩ 서버 허용 범위.** 모델은 상한 안에서 도구를 고를 뿐, 상한을 만들거나 넓히지 못한다.

- 사용자 요청 범위: 그 턴의 사용자 발화가 요구한 것(`files_list` 목록만 / `files` 내용 읽기 포함 / `query_drives`). 같은 모델 호출의 **첫 단계에서 "요청 해석"으로 선언**하고 서버가 기록한다. 이것은 모델이 하고 싶은 도구가 아니라 사용자가 요구한 범위의 해석이다. 선언이 없으면 첫 도구 결정에서 파생하고, 둘 다 없으면 거부한다(가장 좁은 쪽으로 폴백).
- 서버 허용 범위: 권한·tier 정책이 허용하는 최대 범위. `admitted = min(요청 범위, 허용 범위)`. 깎인 결과로 생기는 step 거부는 사용자 400이 아니라 모델에 관찰(observation)로 돌려 같은 run에서 완료하게 한다.
- 상한은 run(턴) 단위로 고정된다. 이후 step의 `intent`·도구 선택은 좁히기만 가능하다(`intent:list` → 그 step은 목록만; `intent:read`·누락 → 효과 없음).
- 이중 강제: Engine step 게이트에 더해 **Chat의 PC 도구 API(dispatch 생성)** 가 서명 claim의 상한을 보고 `files_list`에서는 `kind=read` dispatch를 거부한다. 요구 5의 최종 보장선이다.
- 한계를 명시한다: "사용자가 무엇을 요구했는가"의 의미 해석은 모델이 한다. 서버는 (a) 해석이 선언된 뒤 넓어지지 않음 (b) 권한 초과 불가 (c) 선언·admit 결과의 기록과 UI 표시("목록만 조회합니다")를 보장한다.

- Owner 결정: 툴 사용 턴에는 실행 시한을 두지 않는다 — 진행 중·경과 시간을 보여주고, 실패에만 오류를 보인다(2026-10-24, #5716).

## 3. 단계

- **0단계(완료, 2026-10-24)**: 복원. 키워드 진입 임시 복원, Mesh 전용 자격 복구, Engine ceiling 게이트(#5574·#5653).
- **2차**: 레인 안에서 "요청 범위 선언 → Engine admit → 서명 claim → Chat 전달 → dispatch 경계 강제". 진입은 아직 키워드.
- **3차**: 진입을 일반 스트리밍 호출의 tool-calling(#5597 채널)에 통합. 검증된 PC가 있으면 PC 도구를 도구 목록에 노출하고, 모델이 도구를 고르는 시점에 2차의 선언·admit가 일어난다. 일반 답변은 그대로 스트리밍, 분류 호출 0, 키워드 게이트 제거. PC 도구 실행은 서버가 하므로 BYOK/tier/모델 선택과 무관하다.


### 3차 세부 진행 (2026-10-24)

| 구분 | PR | 배포 여부 |
| --- | --- | --- |
| 3-A — B14 google 스트림 tool_call | #5697 | 배포됨 (b9cf8855) |
| 3-B-1 — Core 파싱 | #5708 | Engine 배포에 포함 |
| 3-B-2 — 직결 레인(보조) | #5709 | 미배포 |
| 3-B-3 — Engine 레인 도구 노출 | #5719 | 미배포 |
| 3-C-1 — declared_plan | #5712 | 배포됨 |
| 3-D-1 — 진행 이벤트 | #5717 | 미배포 |
| 3-D-2 — Chat(진행 중) | 미등록 | 미배포 |
| 3-C-2 — 키워드 게이트 제거 | #5751·#5765 | 코드 조건 충족; 운영 수용은 아래 모든 연산 검증으로 판정 |

### 3-C-2 조건 충족 상태·장부 통합 결정 (2026-10-26)

- 키워드 없는 모델 도구 선택 진입(#5751), 서버 검증 PC 컨텍스트의 Engine 전달·진행 중계(#5765), declared_plan admit·ceiling 강제는 병합된 코드 조건이다. 일반 스트리밍·분류 호출 0·모델/tier/BYOK 보존을 계속 검증한다. 목록·읽기만으로 전체 운영 수용 완료를 선언하지 않으며 드라이브(c)까지 포함한다.
- **장부 통합 결정: `claw_runs` 단일. 새 길(Chat 도구 턴)은 scope admit 시점에 `promote_chat_pc_stream_run`을 재사용해 멱등 등록한다.** 기존 드라이브 엔드포인트의 뒤늦은 승격도 이미 행이 있으면 무해하게 통과해야 한다. 목록·읽기·드라이브·Claw 화면·자동화가 같은 run 행을 본다는 계약 테스트를 구현 PR에 포함한다. 이는 결정이며 해당 수정의 병합·배포·운영 검증 완료 선언이 아니다.

## 4. 2차 수용 기준

1. 선언 `files_list` + `intent:read`/`read_file` → step 거부, read dispatch 0, ops == ['list'].
2. 선언 누락 → 첫 decision에서 파생; 둘 다 없음 → 거부(모델 관찰로 반환, 사용자 400 아님).
3. 권한이 read 불허 + 선언 `files` → `files_list`로 깎여 admit.
4. Chat dispatch: claim 상한 `files_list` + `kind=read` → 거부.
5. 첫 B14 호출 중복 0. 검증 PC 계정의 일반 질문 → Engine 호출 0(스트리밍 경로 무변경).
6. wire 양방향 호환(Engine 새/Chat 옛, Chat 새/Engine 옛). 새 필드는 optional.
7. 별도 분류 호출 0(호출 카운트 테스트).
8. 배포 후 실제 제품: Broker 0·Mesh 전용 계정에서 연산별 각 1회 — (a) 목록: command(list) 1 / read 0 / done, (b) 읽기: read 1 / done / SHA 기준선 일치, **(c) 드라이브(`query_drives`): command 1 / read 0 / done, 검증된 드라이브 목록과 최종 답변 도착**. 각 연산의 실제 응답 모델·fallback_used·run ID·공용 장부/dispatch 연결을 기록한다. 거부 시 코드 포함 로그와 사용자 문장·최종 레코드로 종료하며 준비 중으로 남지 않는다.

기준 1~7은 기존 테스트 파일에 코딩하고 PR 본문에 테스트 이름을 매핑한다. 기준 6은 Chat의 헤더 없는 레거시 경로와 Engine의 레거시 본문 바이트 불변을 각각 증명한다. 기준 8은 배포 후 실제 제품 증빙으로 기록한다. 범위 안내 메시지(`<run_id>_scope`)가 있는 대화에서도 #5567 pending-result GET 복구가 최종 답변을 반환하고 안내문을 결과로 오인하지 않아야 한다.

## 5. 범위·배포

- 변경 후보: Engine `claw_pc_query_step_driver.py`·`orchestration_service.py`, KAgent `pc_query_adapter.py`, Chat `chat_pc_drive.py`(passthrough)·PC 도구 API(dispatch 경계), wire `orchestration_bridge.py`·`client.py`. 기존 테스트 파일에 추가, 새 스위트 금지.
- 배포 순서: Engine(자체 게이트) → Chat(b62 게이트). 각 exact main.
- 금지: 새 Broker 등록 요구, 별도 분류 호출, 키워드 게이트 확장, 모델·tier·BYOK 정책 변경.

## 6. 스트림 계약

### 6.1 전송·기준

이 절은 원격 main `38d538fe77debc3c843c2c4e72bb757d0dbdd347`의 **현재 구현**을 기록한다. CGI-2 계약 테스트 PR 및 오류 전달 수정 PR과 별개인 문서 변경이다. 아래 `file:line`은 이 SHA 기준이며, 이후 코드 변경 시 함께 갱신한다. 배포·실서비스 검증 증빙은 아니다.

- Engine `POST /internal/v1/orchestrate/stream` → HTTP 200, `application/x-ndjson; charset=utf-8`. UTF-8 JSON 객체 하나마다 LF(`\n`) 하나를 붙인다. Engine wire는 SSE가 아니다.
- Chat bridge가 `X-Padiem-PC-Progress: 1`로 opt-in한다(`apps/padiem-chat/app/orchestration_bridge.py:578`, `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/client.py:718`). Engine은 헤더 opt-in과 PC plan/pc_tools 조건을 함께 확인한다(`apps/padiem-ai-engine/app/orchestration_service.py:1784`). 준비 단계 실패는 HTTP JSON 오류이며, 아래 `error`는 스트림 시작 후 NDJSON 오류다.
- 각 정상 레코드의 최상위 키는 정확히 `ok`와 해당 종류 키 두 개다. SDK는 `ok`를 제거하여 bridge에 전달한다. `error`는 값으로 yield하지 않고 예외로 전환한다.
- 표의 JSON은 실제 키를 모두 쓴 형태 예시다. 식별자·문자열·숫자는 예시 값이며, `orchestration`의 하위 객체 확장은 6.3의 Core serializer가 단일 원본이다.

### 6.2 레코드 6종과 Chat 처리

| 종류 | Engine NDJSON JSON 모양 | 필드·검증 | Chat 측 처리 (`file:line`) |
| --- | --- | --- | --- |
| `event` | `{"ok":true,"event":{"event_id":"e1","run_id":"r1","trace_id":"t1","app_id":"b62","kind":"run_started","sequence":1,"timestamp_iso":"2026-10-25T00:00:00+00:00","message":null,"metadata":{}}}` | Engine은 Core `OrchestrationEvent.to_public_dict()`의 9개 필드를 모두 보낸다. ID는 안전한 문자열, `sequence`는 bool이 아닌 양의 정수, `timestamp_iso`는 비어 있지 않은 문자열, `message`는 bounded 문자열 또는 null, `metadata`는 정제된 scalar 값 객체. `kind`는 Core enum(6.3). | `apps/padiem-chat/app/orchestration_bridge.py:285`의 `_safe_events`가 ID 4종·kind·sequence **6개만** 투영한다. `apps/padiem-chat/app/claw_live_events.py:347`에서 run/trace/app 동일성·sequence 증가·terminal 이후 event 금지를 확인하고 누적한다. 이 PC relay는 event를 브라우저로 직접 내보내지 않고 최종 result와 대조한다. |
| `text_delta` | `{"ok":true,"text_delta":{"delta":"답변 조각"}}` | 내부 키는 `delta` 하나, 비어 있지 않은 문자열. 생성: `apps/padiem-ai-engine/app/pc_tools_turn.py:144`. SDK 검증: `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/orchestration_stream.py:47`. | `apps/padiem-chat/app/claw_live_events.py:381`에서 내부 키·문자열을 재검증하고 terminal 이후 text를 거부한다. 브라우저 SSE `event: delta`, `data: {"delta":"답변 조각"}`로 전달한다(`:388`). |
| `pc_progress` | `{"ok":true,"pc_progress":{"pc_run_id":"pc1","dispatch_id":"d1","kind":"read","stage":"accepted","sequence":1,"elapsed_ms":0}}` | 내부 키는 표시된 6개로 고정. ID 2개는 `[A-Za-z0-9_.:-]{1,128}`, `kind`는 `command/read`, `stage`는 `accepted/picked_up/executing/result`. sequence ≥ 1, elapsed_ms ≥ 0인 정수이며 bool 불허. sequence·경과 시간은 dispatch별 emitter 기준(`apps/padiem-ai-engine/app/claw_pc_query_step_driver.py:81`). | `apps/padiem-chat/app/claw_live_events.py:306`에서 필드·값·현재 pc_run_id를 확인한다. `:365`에서 dispatch별 첫 stage=accepted, 이후 sequence와 stage의 엄격한 증가를 요구한다(중간 stage 건너뛰기는 허용). 필요 시 scope_notice를 먼저 보내고 SSE `event: pc_progress`에 내부 객체를 그대로 싣는다(`:373`, `:379`). |
| `heartbeat` | `{"ok":true,"heartbeat":{"run_id":"r1","trace_id":"t1","elapsed_ms":10000}}` | 내부 키는 3개로 고정. ID 형식은 pc_progress와 동일, elapsed_ms ≥ 0인 정수(bool 불허). PC opt-in 스트림에서 10초 동안 queue/task 변화가 없으면 발생하며 경과 시간은 스트림 시작 기준(`apps/padiem-ai-engine/app/orchestration_service.py:287`, `:1887`, `:1896`). | `apps/padiem-chat/app/claw_live_events.py:306`에서 모양을 검증하고 `:361`에서 이미 관찰한 event의 run/trace와 일치해야 한다. SSE `event: heartbeat`에 내부 객체를 전달한다(`:379`). 실행 진척·성공·권한·Core idle 갱신의 증거로 사용하지 않는다. |
| `error` | `{"ok":false,"error":{"code":"engine_internal_error","message":"Orchestration streaming failed.","retryable":false,"metadata":null}}` | Engine 생성 필드는 code(string), message(string), retryable(bool), metadata(object 또는 null) 4개(`apps/padiem-ai-engine/app/service.py:95`). 스트림 오류 serializer는 이 body를 그대로 보낸다(`apps/padiem-ai-engine/app/orchestration_service.py:304`, `:1919`). SDK의 **현재** 검증은 `ok:false`에서 error 전체 schema를 강제하지 않고, code가 `^[a-z][a-z0-9_]{1,63}$`일 때만 보존한다. | `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/orchestration_stream.py:130` → `EngineNdjsonContractError("engine_stream_error", engine_code=...)`; `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/client.py:746` → `PadiemAiEngineClientError("invalid_engine_stream", ...)` + metadata.reason/engine_code. `apps/padiem-chat/app/orchestration_bridge.py:592` → `_engine_error`(`:388`) → `apps/padiem-chat/app/claw_live_events.py:412`에서 SSE error의 code·Chat 작성 message를 보낸다. **현재 Engine message/retryable/metadata는 그대로 전달되지 않는다.** |
| `orchestration` | `{"ok":true,"orchestration":{"execution":{"answer":"최종 답변","route":{},"metadata":{}},"context":{},"app_id":"b62","plan":null,"activated_skill":null,"resolved_tool_ids":[],"evidence":{"claim_count":0,"source_count":0,"assessments":[],"citations":[]},"events":[],"approval_pause":null,"continuation_state":null,"state_machine":{"current_state":null,"transitions":[]}}}` | 표는 Core body의 전체 키 구조이며, 빈 하위 객체·events는 구조 설명용으로 실제 완료 fixture가 아니다. `events`는 1개 이상 필요하고, event 1개 이상을 받은 뒤 terminal body는 정확히 1개여야 한다. approval_pause가 있으면 Engine이 `continuation_ref` 문자열을 추가한다. SDK는 EOF 및 trailing data 부재를 확인한 뒤에만 이 레코드를 yield한다(`apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/orchestration_stream.py:150`, `:162`). | `apps/padiem-chat/app/orchestration_bridge.py:584` → `project_public_orchestration`(`:315`)이 events/approval_pause/continuation_ref/answer만 투영하고 pause를 저장한 뒤 `{"result": B62OrchestrationResult(...)}`로 바꾼다(`:589`). `apps/padiem-chat/app/claw_live_events.py:390`에서 관찰 events 전체·terminal과 최종 events의 일치를 검증한다. pause면 `orchestration_pause` SSE(`:396`), 성공이면 필요 시 최종 delta → on_completed → done SSE(`:400`–`:408`). 일반 text는 중복 출력하지 않고 PC 결과 또는 text 미수신일 때 최종 답변을 추가한다. |

### 6.3 하위 schema·종료 규칙·현재 경계

- `event.kind`의 Core enum: `run_started`, `context_prepared`, `memory_read`, `plan_created`, `skill_resolved`, `tool_resolution`, `tool_started`, `tool_completed`, `tool_failed`, `evidence_attached`, `verification_completed`, `approval_paused`, `run_resumed`, `recovery_started`, `recovery_decided`, `retry_started`, `retry_completed`, `run_cancelled`, `run_failed`, `run_completed`(`packages/padiem-ai-core/padiem_ai_core/orchestration_events.py:37`). event의 정확한 wire serializer는 같은 파일 `:175`; Chat 허용 목록과 투영은 `apps/padiem-chat/app/orchestration_bridge.py:285`가 별도로 강제한다.
- `orchestration`은 별도 스트림용 결과 schema를 만들지 않고 `packages/padiem-ai-core/padiem_ai_core/orchestration.py:231`의 `OrchestrationResult.to_public_dict()`를 재사용한다. execution의 route/metadata, context, plan, activated_skill, evidence의 assessments/citations, events, approval_pause, state_machine.transitions는 해당 Core 객체의 `to_public_dict()` 결과다. resolved_tool_ids는 문자열 배열, plan/activated_skill/approval_pause/continuation_state는 객체 또는 null이다. continuation_state 객체는 `{"status":"상태값","decision_id":null}` 형태이고 decision_id는 문자열 또는 null이다. Engine의 유일한 추가 키는 pause 시 `continuation_ref`(`apps/padiem-ai-engine/app/orchestration_service.py:944`, `:982`)다.
- Chat pause 투영은 `{"status":"paused","continuation_id":"안전한 ID","requirement":"user_confirmation","expires_at":"시간 문자열"}`이며 requirement는 `user_confirmation/external_authorization`, expires_at은 timezone을 포함해 해석 가능한 시각, continuation_ref는 Chat의 continuation 정규식에 맞는 문자열이어야 한다(`apps/padiem-chat/app/orchestration_bridge.py:327`). 정상 완료는 마지막 kind=run_completed와 비어 있지 않은 execution.answer가 모두 필요하다(`:345`).
- SDK 일반 line 한도는 65,536 bytes, lifecycle event 한도는 128개다. text_delta/pc_progress/heartbeat는 lifecycle count에 포함하지 않는다. 정확한 prefix `{"ok":true,"orchestration":`인 단일 최종 line만 8 MiB 한도를 쓴다. 누적 스트림 byte 한도는 두지 않는다(`apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/orchestration_stream.py:14`, `:96`, `:141`). 빈 line·잘못된 UTF-8/JSON·미지원 모양·잘린 스트림·terminal 뒤 데이터는 계약 오류다.
- 정상 흐름은 최초 event → event/표시 레코드들 → orchestration → EOF다. 시작 후 오류는 error로 종료하며 성공 result를 만들어내지 않는다. progress의 result stage와 lifecycle terminal event만으로 완료를 확정하지 않는다. 소비 중단 시 SDK·bridge·relay가 각각 upstream을 닫는다.
- **현재 오류 전달의 결함과 목표를 구분한다.** 위 error 행은 기준 SHA의 실제 코드다. Engine error의 code·message 보존 및 진짜 형식 오류만 invalid_engine_stream으로 분류하는 변경은 별도 오류 수정 PR 범위다. 또한 현재 relay 일반 예외(`apps/padiem-chat/app/claw_live_events.py:414`)는 고정 invalid_engine_stream/message만 보내며 예외 클래스·레코드 종류 cause를 싣지 않는다. 이 문서는 해당 수정이 완료되었다고 주장하지 않는다.


## 7. 고정 마감 폐지 — Owner 결정 (2026-10-26 새벽)

- 툴 사용 턴은 고정 마감으로 끊지 않는다. 하트비트와 PC 단계·경과 시간을 표시하고, 실제 실패·취소·권한 거부는 코드와 사용자 문장으로 알린다. 하트비트는 실행 성공이나 권한·진척의 증거가 아니다.
- **예측 → 질문 → 진행 → 초과 알림**: 예상 소요 시간·분량을 안내하고 필요한 진행 선택을 질문한 뒤 진행 상태를 보여준다. 예측 시간을 넘으면 계속 진행 중임을 알리며, 초과 자체를 timeout/503·실패·자동 재실행으로 바꾸지 않는다.
- 큰 파일은 승인된 경로·권한 안에서 조각 읽기를 사용하거나 컴2 실행 경로로 처리한다. 응답·메모리 한도를 이유로 전체 작업을 조용히 잘라내지 않으며 부분 결과와 남은 작업을 표시한다. 새 기기·경로 권한을 부여하지 않는다.
- 목록은 페이지네이션과 페이지별 개수 상한으로 나누어 반환하고 다음 페이지·남은 항목을 표시한다. 개수 상한은 전체 목록의 누락을 숨기거나 완료로 오인시키는 총량 마감으로 사용하지 않는다. 구체 값과 wire 변경은 구현 PR에서 계약 테스트로 검증한다.
- 이 절은 목표 정책이다. 현재 남아 있는 ToolSpec/idle 제한·Cloudflare 플랫폼 제한이 제거됐다고 주장하지 않으며, 적용 변경·실제 운영 증빙은 별도 구현 PR과 정식 게이트에 기록한다.
