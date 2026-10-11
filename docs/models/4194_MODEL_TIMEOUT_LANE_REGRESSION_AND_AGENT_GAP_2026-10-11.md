# #4194 모델 600초 소스 정책 점검 및 장시간 Agent/Task 미완료 경계 — 2026-10-11 KST

> 현재 결과: **기본 모델 호출 지연 경계에 대한 정적 소스 회귀 검사 완료**, **전 제품 운영 완료/Agent 영속 실행 완료 아님**. 이 문서는 #4194 종료 증명이 아니라 남은 실제 작업을 구체화한 단계 검증 자료다.

## 1. 이 작업에서 검증한 내용

`packages/padiem-ai-core/tests/test_4194_model_lane_timeout_guard.py`는 모델 API/Secrets/Cloudflare를 전혀 호출하지 않는 Python 소스계약 테스트다. 최신 main 기준 코드에서 아래 구분이 유지되는지 자동 확인한다.

| 구간 | 검증 파일 | 모델 대기 소스 기본값 |
|---|---|---|
| B14 provider read | `apps/korean-ai-platform/app/pilot/b14_timeout_policy.py` | per-read chunk **600s**, retry/fallback chain 45s 분리 |
| Core → B14 completed + SSE | `packages/padiem-ai-core/padiem_ai_core/b14_execution.py`, `b14_streaming.py` | **600s** idle; SSE header/chunk마다 재설정되는 경계 |
| Engine → B14 | `apps/padiem-ai-engine/worker.py` | **600s** |
| Chat B62 → B14 | `apps/padiem-chat/app/worker_config.py`, `wrangler.toml` | streaming 및 completed **600s** 소스 설정 |
| Living Fiction | `apps/living-fiction/app/ai/openai_compat.py` | **600s** |
| Living Travel | `apps/living-travel/app/ai/openai_compatible.py`, `config.py` | **600s** |
| Living Learning | `apps/living-learning/app/ai/padiem_core.py`, `config.py` | **600s** |
| Personal Edition | `apps/personal-edition/app/ai/external.py` | **600s** |
| Agent Context | `agent_definition.py`, `execution_context.py`, `agent_runtime.py`, `orchestration.py` | **900s 기본 wall / 3600s 최대**, 여전히 fixed-wall 및 `asyncio.wait_for` 존재 |
| 비모델 도구 | `apps/padiem-ai-engine/app/calendar_port_cp_lease.py`, `drive_case_pdf_service.py` | 도구/OAuth/파일 변환은 별도 짧은 제한 유지 |

위의 비교는 **정적 소스 default**에 대한 점검이다. 실제 운영 Cloudflare binding, registry override, Provider 계정/네트워크, PDF/다른 제품 경로의 E2E까지 통과했다는 뜻이 아니다. 제품별 직접 모델 호출 경로 전수 감사에서 새 호출자가 발견되면 이 표와 테스트를 함께 확장해야 한다. 단지 `timeout=600`이 있다고 실제 600초 모델 응답을 얻을 수 있다고 주장하지 않는다.

`b14_streaming.py`의 SSE chunk 경계는 이미 기존 `test_b14_streaming.py`에 **건강한 진행 스트림이 총 대기보다 길어도 성공**하고 **지연/무응답은 종료**하는 소규모 테스트가 있다. 이번 PR은 그 경계를 다른 제품과 함께 회귀 검사한다. 긴 실유료 모델을 반복 호출해 시간을 재는 테스트는 추가하지 않았다.

## 2. 절대 혼동하면 안 되는 두 시간 제한

- **Model inference idle 600s:** 건강한 모델 응답이 도착하면 유휴 제한이 갱신된다. B14 최초 모델 시도의 역사적 45초 임의 강제중단은 #4200에서 제거되었다.
- **Agent/Task 전체 wall 900~3600s:** `BoundedAgentRuntime.run`은 `max_wall_seconds`를 검사하고 `asyncio.wait_for`로 각 단계/도구를 제한한다. `OrchestrationService`도 Agent 및 일반 실행, 재개 경로에 `asyncio.wait_for(timeout=request.context.timeout_seconds)`가 남아 있다. 지금은 **ZCode식 no-fixed-wall durable async run 지원을 증명하지 못했다**.
- **OAuth / Tool / search / network connect/write/lease:** 사용자가 취소하거나 연결이 실패했을 때 자원을 회수하는 짧은 경계다. 이를 모델 추론 제한과 혼동해 `timeout=None`으로 일괄 변경하지 않는다.

## 3. #4194를 실제로 종료하기 위한 나머지 작업 (반드시 구현/검증)

1. **직접 모델 호출자 전수 검색과 경로별 실효 설정:** source 설정과 실제 Worker binding/service binding/registry override가 같은지 READ-ONLY로 확인하고, B14 경유/직접 제공업체 호출·B62/Engine/P01/Claw/Living/Personal의 모델/비모델 경계를 구분한다. 새 호출자는 이 테스트의 경로 목록에 추가한다.
2. **Agent/Task durable execution:** 신뢰할 수 있는 run ID와 작업 소유자, 영속 checkpoint 및 fencing lease, 진행 이벤트/heartbeat/inactivity watchdog, 외부 side effect 재시도 방지, 승인 일시정지→재개, 사용자 취소 및 timeout 후 idempotency/과금 중복 방지가 필요하다. 현재 `agent_recovery.py`는 외부 도구 side effect 재시도 금지 정책까지만 표현한다. **실제 영속 저장·재개와 분산 실행 인가를 붙이기 전에 부모/자식 wall 제한을 제거하지 않는다.**
3. **결정적 실패/복구 검증:** virtual-clock/fake SSE에서 45초 초과 정상 생성, 600초 유휴 중단, 진행 간 reset, cancel/stop/restart/lease 만료/중복 실행/Provider 429·504를 각 경계별로 테스트하고 최소한의 scoped CI 통과.
4. **운영 인증:** 해당 제품의 실제 활성 버전·비밀값 이름·service binding 보존을 읽고, 권한 있는 synthetic 계정에서 실제 장시간 run/재개/취소를 검증. 비용·모델 호출은 개별 승인·통제; Kira 및 DeepSeek 반복 실험 금지. 실제 운영이 확인되기 전 #4194 **OPEN**.

## 4. 변경 범위

이번 개선은 **test + 문서**만 수정한다. 모델 기본값·Agent limit·Cloudflare runtime·Secrets Store·R2/D1·고객 원본 데이터·유료 API 호출·운영 배포는 변경하지 않는다. 예전 B62 Worker `PADIEM_CHAT_TIMEOUT_SECONDS=600`과 B14 배포 검증은 #4194의 이전 댓글에 남아 있지만, 이 테스트만으로 새 버전 운영 여부를 재인증하지 않는다.

```text
SOURCE_DEFAULT_REGRESSION_GUARD=PASS_WHEN_CI_GREEN
AGENT_NO_FIXED_WALL=NOT_IMPLEMENTED
DURABLE_LEASE_CHECKPOINT_HEARTBEAT_CANCEL=NOT_IMPLEMENTED
CROSS_PRODUCT_LIVE_600S=UNVERIFIED
LIVE_PAID_PROVIDER_CALLS=0
PRODUCTION_MUTATION=0
ISSUE_4194=OPEN_UNTIL_ALL_ACCEPTANCE
```
