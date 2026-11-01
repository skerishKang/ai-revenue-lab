# PC 사전 위임 하네스 — 2026-11-01

기준: #6516 행동 전 근거 확인과 행동 후 결과 검증 브랜치 위 후속 작업.
#6007 본문과 댓글 3개를 읽었다. 기존 로컬 PC 쓰기 권한은 연결된 소유자의
EXTERNAL_AUTHORIZATION이며, 이번 폴더 규칙은 장치·도구 권한을 새로 부여하지 않는다.

## 판단과 확인

1. Engine 공통 `ActionGuardedPCQueryStepDriver._decision`에서 사용자 의도·대상 근거부터 검사한다.
   파일·웹·메일 속 지시는 위임 규칙이 있어도 근거가 되지 않는다.
2. 그 검사를 통과한 쓰기·이동·삭제에만 서버가 읽은 사용자 규칙을 적용한다.
   같은 PC·폴더·행동이어야 하고, 이동은 출발·도착 모두 허용 범위 안이어야 한다.
   `ask` 규칙은 `allow`보다 우선한다.
3. 범위 밖·꺼진 규칙·항상 확인은 도구를 실행하지 않고 일반 질문으로 끝난다.
   사용자의 다음 “네”는 정확한 경로·이동 목적지가 일치하는 새 요청으로 처리한다.
   pause/resume 상태나 두 번째 승인 버튼은 만들지 않는다.
4. 실행한 행동은 2단계 결과 검증을 계속 거친다.

규칙을 한 번도 설정하지 않았거나 빈 설정이면 기존 1단계 동작을 유지한다.
즉, 명시적인 사용자 요청이 기존 근거 검사를 통과하면 그대로 실행한다.
규칙을 등록한 뒤 끄면 그 행을 남겨 자동 실행 대상으로 되돌아가지 않게 한다.
설정은 각 요청에서 소유자 저장소를 읽으며 변경은 이후 요청에 적용된다.
조회 장애는 빈 설정으로 간주하지 않고 `available:false`로 전달해 대화로 확인한다.

SEND·외부 서비스 기록 변경은 폴더 위임에서 제외한다.
검토된 외부 connector WRITE는 기존 Core `USER_CONFIRMATION`을 사용하고,
로컬 PC 세 도구는 기존 외부 소유자 권한과 공통 하네스로 판단하므로 중복 버튼이 없다.
읽기·검색은 바꾸지 않았다.

## 설정과 저장

- 화면: Chat·Claw 공용 설정의 **PC에 맡길 일**. PC·폴더·행동·맡기기/항상 물어보기와 목록 켜기/끄기.
- API: `GET/PUT /api/account/pc-delegations`. 로그인 소유자·기존 Origin 검사를 사용한다.
- 저장: 기존 `PADIEM_CHAT_DB`의 `padiem_pc_delegations`, `user_id`별 JSON 한 행.
  컴2에서는 기존 SQLite adapter를 사용한다.
- 스키마: `{version:1,rules:[{id,device_id,folder,actions,mode,enabled}]}`.
  SEND 행동과 브라우저의 내부 availability/소유자 필드는 저장할 수 없다.
- Chat/Claw → bridge/SDK/Core DTO → Engine의 별도 `pc_delegation` 필드로 전달한다.
  모델 입력에 설정을 추가하지 않는다. 재생 식별값에는 정책을 포함한다.
- 절대 폴더와 도구의 상대 경로 비교는 같은 소유자·PC의 서명된 context
  `delegation_roots`로 해결한다. 실제 루트 경로는 모델 입력에서 제외한다.

## 반영과 검증

운영 반영 레인은 `081_pc_delegations.sql` 적용과 Chat·P01 코드 반영이 필요하다.
이 작업에서는 마이그레이션 실행·배포·PR 생성을 하지 않았다.
`d1_sqlite.py`와 `local_cpython.py`는 수정하지 않았다.

핵심 시험: Engine 220 + Chat 설정/API/UI/context 87 + SEND/Core 26 = **333 passed**.
JSON·스트리밍·native 일반·native 스트리밍, 미설정 기본값, 위임 안/밖,
끄기, 항상 확인, 다른 PC, 저장소 장애, 인젝션, 이동 양쪽 범위, 질문 후 새 요청을 검증했다.
UI는 실제 JavaScript DOM harness로 저장·목록·끄기·로그인 전환·늦은 응답을 검증했다.
위임 판단을 제거한 격리 실행에서는 범위 밖 JSON·스트리밍 시험 2개가 예상대로 실패했다.
추가 SDK/기존 route 회귀도 통과했다. 운영 PC 실행은 하지 않았다.

## 변경 파일

- `apps/korean-ai-code-agent/src/kagent/connector_projection.py`
- `apps/korean-ai-code-agent/src/kagent/p01_adapter.py`
- `apps/korean-ai-code-agent/src/kagent/p01_orchestration_client.py`
- `apps/korean-ai-code-agent/tests/test_connector_projection.py`
- `apps/korean-ai-code-agent/tests/test_pc_delegation_send_boundary.py`
- `apps/padiem-ai-engine/app/claw_pc_query_step_driver.py`
- `apps/padiem-ai-engine/app/orchestration_idempotency_service.py`
- `apps/padiem-ai-engine/app/orchestration_identity_service.py`
- `apps/padiem-ai-engine/app/orchestration_service.py`
- `apps/padiem-ai-engine/app/orchestration_wire.py`
- `apps/padiem-ai-engine/app/pc_action_delegation.py`
- `apps/padiem-ai-engine/app/pc_action_harness.py`
- `apps/padiem-ai-engine/app/pc_tools_turn.py`
- `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client/client.py`
- `apps/padiem-ai-engine/tests/test_orchestration_wire.py`
- `apps/padiem-ai-engine/tests/test_pc_action_delegation.py`
- `apps/padiem-ai-engine/tests/test_pc_delegation_context_projection.py`
- `apps/padiem-ai-engine/tests/test_pc_delegation_end_to_end.py`
- `apps/padiem-ai-engine/tests/test_pc_delegation_wire.py`
- `apps/padiem-chat/app/app_factory.py`
- `apps/padiem-chat/app/canonical_orchestration_bridge.py`
- `apps/padiem-chat/app/chat_pc_drive.py`
- `apps/padiem-chat/app/claw_general_routes.py`
- `apps/padiem-chat/app/oracle_mesh_read_return_routes.py`
- `apps/padiem-chat/app/orchestration_bridge.py`
- `apps/padiem-chat/app/orchestration_routes.py`
- `apps/padiem-chat/app/pc_delegation_routes.py`
- `apps/padiem-chat/app/pc_delegation_store.py`
- `apps/padiem-chat/migrations/081_pc_delegations.sql`
- `apps/padiem-chat/static/index.html`
- `apps/padiem-chat/static/locale.js`
- `apps/padiem-chat/static/pc-delegation-settings.css`
- `apps/padiem-chat/static/pc-delegation-settings.js`
- `apps/padiem-chat/tests/pc_delegation_settings_harness.js`
- `apps/padiem-chat/tests/test_5015_pc_read_dispatch.py`
- `apps/padiem-chat/tests/test_5573_pc_pairing_directory_dispatch.py`
- `apps/padiem-chat/tests/test_pc_delegation_settings.py`
- `apps/padiem-chat/tests/test_pc_delegation_settings_ui.py`
- `apps/padiem-chat/tests/test_pc_delegation_transport.py`
- `packages/padiem-ai-core/padiem_ai_core/orchestration.py`
- `packages/padiem-ai-core/padiem_ai_core/pc_delegation.py`
- `docs/operations/PC_DELEGATION_20261101.md` (이 보고서)
