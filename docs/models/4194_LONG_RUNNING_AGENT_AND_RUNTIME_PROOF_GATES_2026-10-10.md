# #4194 ZCode형 SSE 모델 유휴 감시 및 남은 장시간 작업 운영 게이트

2026-10-10 KST · `skerishKang/ai-revenue-lab` · 상위 [#4194](https://github.com/skerishKang/ai-revenue-lab/issues/4194), 모델 전달 [#4191](https://github.com/skerishKang/ai-revenue-lab/issues/4191), 운영 배포 [#4186](https://github.com/skerishKang/ai-revenue-lab/issues/4186).

## 1. 기존 PR #4200과 이번 후속 구현의 차이

PR #4200은 B14/Chat/Core/Engine/P01/Living/Personal의 소스 모델 기본 응답유휴를 600초로 변경하고 첫 B14 모델 요청의 무조건 45초 취소를 없앴다. 하지만 Cloudflare Workers Service Binding / JS Fetch 호환 전송은 HTTPX read 단계의 `timeout` 의미와 다를 수 있었다.

후속 Core `b14_streaming.py`에는 전송 구현에 독립적인 두 유휴 감시를 추가했다.

1. **응답 헤더 대기:** `AsyncExitStack.enter_async_context(client.stream(...))`에만 별도 `asyncio.timeout(config.timeout_seconds)`을 적용. 이 시계는 첫 헤더 이후 종료되므로 SSE 총 실행시간 제한이 아니다.
2. **각 수신 chunk 대기:** `response.aiter_bytes().__anext__()`에 별도 `asyncio.timeout(config.timeout_seconds)`을 적용. chunk 수신 때마다 독립 타이머가 초기화되므로 정상 송신 중인 장시간 스트림이 임의 종료되지 않는다.
3. **취소·자원 정리:** `asyncio.CancelledError`는 삼키지 않으며 async client/response scope를 정상 닫는다. 유휴 timeout은 `B14ExecutionError("upstream_timeout")`으로 분류. 오류 문자열과 고객 메시지 노출 방지.
4. **모든 호출자에게 적용:** Core `B14StreamingClient`를 사용하는 직접 HTTPX 및 Worker Service Binding 호환 어댑터. `max_response_bytes`, `[DONE]` 검증, idempotency/usage/retry 정책 유지.
5. 테스트: 1초보다 총 경과시간이 긴 0.65+0.65초 정상 이벤트 스트림 성공; 1.15초 무응답 스트림 504 분류; 1.15초 헤더 지연 감시; 사용자 조기 취소 및 stream closure.

Core의 **AgentExecutionBudget 기본 180→900초**, **SkillExecutionBudget 기본 120→900초**, **AgentDelegationRequest 기본60→900초**로 #4200의 ExecutionContext 900초에 맞췄다. 명시적 60초 narrower child 권한은 유지되고, 각 예산 최대3600초 및 parent delegation 상한 검증을 제거하지 않았다.

Chat의 `wrangler.toml`에 남은 `PADIEM_CHAT_TIMEOUT_SECONDS="20"`을 `"600"`으로 수정. 이 설정은 Worker 기본값보다 높은 우선순위로 동작하므로 source default만 바꾸면 구버전 20초가 재도입되는 실효 결함이었다. **`PADIEM_CHAT_RUNTIME_MODE="mock"`, `PADIEM_CHAT_LIVE_ENABLED="false"`는 유지**하여 무단 실운영 활성화 없음. 별도의 Runtime/Production 배포 설정의 명시적 override는 이 PR만으로 자동 수정되지 않는다.

## 2. 확인된 검증

- 오프라인 MockTransport Core SSE/event idle + 취소 테스트 24 PASS.
- AgentRuntime/AgentDefinition/AgentDelegation/SkillPackage/AgentExecutionBridge와 SSE 결합 79 PASS.
- Chat worker config, completed timeout, mock-deploy guard, service binding 37 PASS.
- 실제 외부 모델 호출, 유료 모델 호출, Kira/DeepSeek 호출 모두 0건.
- `git diff --check` 및 py_compile / CI exact-head 필수 검증 필요.

## 3. 아직 완료 아님 — 사용자에게 정확히 밝혀야 하는 일

### 운영 환경
Cloudflare CLI `wrangler deployments list --json`를 B14·Chat·Engine 각각 읽기 전용으로 실행했으나, 이 환경에서 JSON 출력을 받지 못했으며 B14 CLI는 종료코드 1이었다. 따라서 **활성 Worker 배포 버전·소스 SHA·실효 binding/registry/env 설정은 증명되지 않았다.** Secrets 값 노출이나 변경은 없었다.

별도 Production 배포 승인 후 필요한 작업: 활성 계정/프로필 진위 확인 → B14/Engine/Chat Worker 소스 일괄 배포 계획 → 명시적 env overrides readback 및 설정값 이동 → 배포 버전 GET-only 증명 → 비용이 승인된 실모델 one-shot 시험(단 Kira/DeepSeek는 별도 지시 전 제외).

### 장시간 Agent/Task 완전한 무제한 수명
Core `OrchestrationService`는 `asyncio.wait_for(..., timeout=context.timeout_seconds)`, `AgentPlanExecutor`는 `budget.max_wall_seconds`를 사용한다. 이번 후속 수정은 **defaults 간 900초 정합화**까지이며 실제 실행 시계는 그대로 남아 있다. external coding runner도 timeout 900~3600초 계약이 남는다. 이 상태를 ZCode `timeout:{kind:"none"}` 구현 완료로 발표하는 것은 잘못이다.

**정확한 다음 아키텍처 작업:** trusted scheduled backend에서 `run_id/status/progress/heartbeat/approval_pause/resume/cancel/idempotency`가 영속되는 장시간 작업을 도입해야 한다. Model inference 단일 호출은 SSE idle watchdog, 코딩 에이전트 전체 작업은 durable task lease/inactivity watchdog으로 분리한다. 사용자 승인과 자원/과금 가드는 보존한다. Cloudflare 응답 연결 끊김과 worker 종료 후에도 run 상태가 살아야 한다.

## 4. 범위 및 결정권
코드 PR squash 병합과 Production 배포는 별도 단계. `KIRA_LIVE=0`, `DEEPSEEK_LIVE=0`, `OTHER_PROVIDER_LIVE=0`, `PRODUCTION_DEPLOY=0`, `SECRETS_MUTATION=0`. #4194 이슈는 장기 작업 수명·운영 증명 완료 전까지 OPEN 유지.
