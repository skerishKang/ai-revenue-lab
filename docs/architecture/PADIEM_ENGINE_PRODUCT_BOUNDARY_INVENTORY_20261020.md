# PADIEM Engine 제품 경계 인벤토리 (READ ONLY)

- 이슈: [#5151](https://github.com/skerishKang/ai-revenue-lab/issues/5151) lane C (Engine 경계 담당)
- 작성일: 2026-10-20
- 범위: `apps/padiem-ai-engine/**` 의 **제품 고유** 표면 목록. **코드 변경 없음.**
- 상태: READ ONLY 인벤토리 + 좁은 분리 계획 제안

이 문서는 [#5151](https://github.com/skerishKang/ai-revenue-lab/issues/5151) 이 지정한 lane C의 첫 산출물이다:
"`apps/padiem-ai-engine/**`의 제품 고유 StepDriver 목록/사용자 이벤트가 먼저 READ ONLY, A 버그와 스코프가 다르면 독립 계획."

원칙(AGENTS.md·[P01_B62_SHARED_RUNTIME_BOUNDARY_LOCK_2409.md](../architecture/P01_B62_SHARED_RUNTIME_BOUNDARY_LOCK_2409.md)):
Engine은 **장기 실행·승인 대기·교차 런타임** 경로만 남고, 제품(Chat/Claw/B66)은 제품 Worker에서 직접 실행한다.
이번 인벤토리는 그 경계를 **代码 근거로 확정**하기 위한 것이며, 그 자체로 동작을 바꾸지 않는다.

## 1. 요약 결론

| 질문 | 근거 | 결론 |
| --- | --- | --- |
| Engine의 제품 고유 표면은 무엇인가 | §2 | **제품 신원(app_id / agent_id)과 그에 묶인 툴 바인딩·StepDriver** |
| Engine의 사용자 이벤트 어휘는 제품 고유인가 | §3 | **아니다.** 이벤트 종류 21개는 전부 `padiem_ai_core` 의 제품 중립 계약이다 |
| 분리 경계는 이벤트 계약인가, 제품 바인딩인가 | §2·§3 | **제품 바인딩(identity + binding)이다.** 이벤트를 옮길 필요가 없다 |
| Chat/Claw의 기존 PC 실행 경로가 이 계획의 영향받는가 | §4 | **아니다.** 이번 계획은 `apps/padiem-ai-engine/**` 밖을 건드리지 않는다 |

핵심 발견: **Engine의 "제품 전용"은 이벤트 어휘가 아니라 툴 바인딩과 신원 상수다.**
따라서 분리 작업의 최소 단위는 이벤트 마이그레이션이 아니라, **제품 신원 분기(StepDriver·tool binding·app_id 조건)의 소유권 이전**이다.

## 2. 제품 고유 표면 인벤토리 (`apps/padiem-ai-engine/app/`)

### 2.1 제품 신원 상수

| 모듈 | 파일:행 | 상수 | 값 |
| --- | --- | --- | --- |
| `claw_pc_query_step_driver.py` | 21 | `CLAW_APP_ID` | `b54-padiem-claw` |
| `claw_pc_query_step_driver.py` | 30 | `CHAT_APP_ID` | `padiem-chat` |
| `claw_pc_query_step_driver.py` | 31 | `CHAT_PC_QUERY_AGENT_ID` | `agent:padiem:chat-pc-query@1` |
| `claw_desktop_step_driver.py` | 103-104 | `CLAW_APP_ID` / `DESKTOP_AGENT_ID` | `b54-padiem-claw` / `agent:padiem:claw-desktop@1` |
| `connector_bindings.py` | 94-117 | `GMAIL_REFERENCE_APP_ID` + reader agent ids | `b54-padiem-claw` / `agent:padiem:claw_{mail,drive,telegram,slack,calendar}_reader@1` |
| `hark_office_p01_tool_binding.py` | 22-23 | `APP_ID` / `AGENT_ID` | `hark-office-local-p01` / `agent:padiem:hark-office-p01@1` |
| `web_xlsx_p01_tool_binding.py` | 20-21 | `APP_ID` / `AGENT_ID` | `padiem-web-xlsx-p01` / `agent:padiem:web-xlsx-confirm@1` |
| `web_xlsx_quote_write_tool_binding.py` | 27-28 | `APP_ID` / `AGENT_ID` | `padiem-web-xlsx-write-p01` / `agent:padiem:web-xlsx-quote-write@1` |
| `approval_smoke_binding.py` | 33-34 | `APPROVAL_SMOKE_APP_ID` / `APPROVAL_SMOKE_AGENT_ID` | `b54-engine-approval-smoke` / `agent:padiem:approval_smoke@1` |
| `agent_preview_authority.py` | 54 | `PREVIEW_APP_ID` | `engine-a5-agent-synthetic` |
| `auth_boundary_diagnostic.py` | 81, 85 | `CHAT_WORKER` / `P01_APP_ID` | `padiem-chat` / `b54-padiem-claw` |

### 2.2 제품 조건 분기 (런타임 동작이 제품마다 달라지는 지점)

| 파일:행 | 분기 | 제품 전용 성격 |
| --- | --- | --- |
| `claw_pc_query_step_driver.py:207` | `if app_id == CLAW_APP_ID` | Claw/Chat PC 쿼리 툴 바인딩 선택 |
| `orchestration_service.py:79-82` | `_PC_PLAN_AGENT_IDS` | PC 계획 인자 검증 대상 agent |
| `orchestration_service.py:370` | `_PC_QUERY_STREAM_AGENT_IDS` | 스트림 오너 허용 agent |
| `orchestration_service.py:572-587` | `_validate_pc_plan_tool_arguments` | PC 계획 `device_id` 계약(§5) |
| `execution_admission_service.py:394` | `binding.app_id in (CLAW_APP_ID, CHAT_APP_ID)` | 제품 범위 admission |
| `tool_execution_service.py:631, 665, 737, 748` | `app_id == "padiem-web-xlsx-p01"` / `"padiem-web-xlsx-write-p01"` | XLSX 계열 툴 실행 분기 |
| `hark_office_p01_tool_binding.py:155` | `if app_id == APP_ID` | Hark Office 바인딩 |
| `web_xlsx_p01_tool_binding.py:198` | `if app_id == APP_ID` | Web XLSX 바인딩 |
| `web_xlsx_quote_write_tool_binding.py:234` | `if app_id == APP_ID` | XLSX 견적 쓰기 바인딩 |
| `approval_smoke_binding.py:162` | `if app_id == APPROVAL_SMOKE_APP_ID` | 승인 스모크 바인딩 |
| `agent_runtime_activation.py:33` | `AGENT_REFERENCE_CONSUMERS` | `("b54-padiem-claw", "b62-padiem-chat")` |
| `document_runtime_activation.py:84` | `DOCUMENT_REFERENCE_CONSUMERS` | `("b54-padiem-claw", "b62-padiem-chat")` |
| `multimodal_runtime_activation.py:58` | `MULTIMODAL_REFERENCE_CONSUMERS` | `("b54-padiem-claw", "b62-padiem-chat")` |

### 2.3 제품 고유 StepDriver 목록

| StepDriver / binding | 제품 | 성격 | 분리 우선순위 |
| --- | --- | --- | --- |
| `claw_pc_query_step_driver` | Claw(`b54-padiem-claw`) / Chat(`padiem-chat`) | PC 드라이브·목록·파일 읽기. 제품 서명 콜백을 **Engine 밖**으로 보낸다 | **높음** (Chat/Claw 직결 대상) |
| `claw_desktop_step_driver` | Claw | 데스크톱 캡처·입력 | 중간 |
| `connector_bindings` (Gmail/Drive/Telegram/Slack/Calendar reader) | Claw | 제품 커넥터 리더 agent | 중간 |
| `web_xlsx_p01_tool_binding` | `padiem-web-xlsx-p01` | 웹 XLSX 확정 | 낮음 |
| `web_xlsx_quote_write_tool_binding` | `padiem-web-xlsx-write-p01` | B66 견적 쓰기 | 낮음 |
| `hark_office_p01_tool_binding` | `hark-office-local-p01` | Hark Office P01 | 낮음 |
| `approval_smoke_binding` | `b54-engine-approval-smoke` | 승인 스모크 | 낮음 |
| `agent_preview_authority` | `engine-a5-agent-synthetic` | 합성 미리보기 | 낮음 |

## 3. 사용자 이벤트 표면 (제품 중립 확인)

`packages/padiem-ai-core/padiem_ai_core/orchestration_events.py` 의 `OrchestrationEventKind` 는 21종이며
전부 **제품 중립**이다.

```
run_started, context_prepared, memory_read, plan_created, skill_resolved,
tool_resolution, tool_started, tool_completed, tool_failed, evidence_attached,
verification_completed, approval_paused, run_resumed, recovery_started,
recovery_decided, retry_started, retry_completed, run_cancelled, run_failed,
run_completed
```

- 제품 이름, 제품 ID, 제품 전용 이벤트 종류는 **이 어휘에 없다**.
- Engine은 이벤트를 새로 만들지 않는다. `padiem_ai_core` 의 계약이 소유한다.
- **결론: 사용자 이벤트는 분리 대상이 아니다.** 분리 작업은 이벤트 어휘를 건드리지 않는다.

## 4. 고정 경계 (이번 계획이 건드리지 않는 것)

- Chat/Claw/B66의 기존 **동기 실행** 경로와 #5015/#4976의 PC 실행 경로. 이 인벤토리는 `apps/padiem-ai-engine/**` 밖을 수정하지 않는다.
- Control Plane의 identity / tenant / entitlement, Broker의 실행 지점·device/grant/revocation.
- BYOK 고객 선택 경로·로그·모델 공개·코드 실행 권한.
- `padiem_ai_core` 의 이벤트·실행 계약.
- 배포·운영 설정·COM2·Mesh ON·Oracle 복구.

## 5. 좁은 분리 계획 제안 (실행 전 검토용)

**제안 A (추천) — 제품 툴 바인딩 소유권 이동, 계약은 그대로**

1. 제품 툴 바인딩과 StepDriver를 **제품 소유 패키지**로 옮긴다. 대상: `claw_pc_query_step_driver`, `claw_desktop_step_driver`, `connector_bindings`, `web_xlsx_*`, `hark_office_p01_tool_binding`.
2. `padiem_ai_core` 의 실행·이벤트 계약은 **그대로 둔다**. 이벤트를 옮기지 않는다(§3).
3. Engine은 **durable long-running / pause-resume / cross-runtime** 경로만 유지한다. 제품 툴 바인딩은 Engine이 참조하지 않는다.
4. 이동은 **파일 이동이 아니라 참조 이동**이다. Engine의 공개 계약(`/internal/v1/orchestrate` 등)과 요청·응답 형태는 바꾸지 않는다.
5. 각 이동은 **기존 동작 유지**를 검증 가능한 집중 테스트로 고정한다. 제품 신원 상수(`app_id`/`agent_id`) 값은 그대로 유지한다.

**제안 B — Core 직결(、产品 Worker ↘ shared Core)**

1. Chat/Claw Worker가 공유 Core Agent/Tool runtime으로 직접 동기 실행한다.
2. B14 관리형 모델은 B14로, 고객 선택 제공자는 기존 BYOK_DIRECT로, PC 실행은 기존 Broker/Mesh/Connector로 간다.
3. Engine은 장기 실행·승인 대기·교차 런타임 전용.
4. Core에 **bounded 직접 실행 entrypoint** 하나만 추가하고, 기존 제품 구현을 복제하지 않는다.

**추천: 제안 A → 제안 B 순서.** 제안 A가 신원·바인딩 소유권을 정리하고, 그 위에서 제안 B가 실행 경로를 옮긴다. 두 단계를 한 번에 하면 회귀 원인을 구분할 수 없다.

## 6. 다음 단계와 금지

- 다음: lane D(독립 검증) 담당과 이 인벤토리를 공유하고, **제안 A의 1단계(가장 작은 제품 바인딩 1개) 소유권 이동** 범위를 확정한다. 한 번에 하나만 옮긴다.
- 기준선: `docs/architecture/P01_B62_SHARED_RUNTIME_BOUNDARY_LOCK_2409.md` 의 권한/집행 경계 코드 증거 범위를 변경하지 않는다.
- 금지: 제품 계층·코드·배포·권한·모델 선택·고객 사용 조건의 변경. 신규 Router/Broker/Worker/DO/Workflow. 즉시 별도 배포.
