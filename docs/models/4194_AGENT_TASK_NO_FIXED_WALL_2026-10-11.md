# #4194 — Agent/Task no-fixed-wall 계약 (2026-10-11 KST)

**범위: 소스 구현 + 오프라인 fake-clock/단시간 실시간 검증.** 운영 배포, Secret 변경,
D1/R2 변경, 유료 모델 실호출은 이 문서/PR에 포함되지 않는다.

## 왜 바꾸는가

이전까지 Agent 실행은 **누적 wall clock** 예산으로 잘렸다.

- `BoundedAgentRuntime`이 `max_wall_seconds`(기본 900, 최대 3,600)를 *총 경과시간*으로 차감해
  초과 시 `MAX_WALL_TIME`으로 종료.
- `OrchestrationRunner`가 `asyncio.wait_for(executor.execute(...), timeout=context.timeout_seconds)`로
  Agent/Task 브리지 실행을 **고정 wall-time**으로 강제 중단.

그래서 정상적으로 계속 진행 중인 장시간 작업(긴 생성, 다단계 Tool 실행)도 고정 시간에 도달하면
실패로 끝났다. 이는 ZCode 기준(`Agent/Task` `timeout: {kind:"none"}` + parent abort +
inactivity watchdog)과 다르다.

## 새 계약 (구현 완료)

1. **누적 wall cap 없음.** Agent/Task 실행에 총 경과시간 상한이 없다.
   `max_wall_seconds`는 *유휴(inactivity) 창*으로 재정의된다.
2. **진행 판정은 서버가 관측한 사실만.** 진행 이벤트는 session/driver 결정 반환, Tool 결과 수신,
   durable checkpoint 저장 성공 3가지다(모델 자기보고 아님).
   구현: `padiem_ai_core/agent_progress.py` (`AgentProgressTracker`, `await_with_agent_progress`,
   `AgentIdleTimeoutError`).
3. **정지한 실행은 fail-closed.** 유휴 창 동안 진행이 없으면 `MAX_WALL_TIME`으로 종료하며
   성공/재개 가능으로 표시하지 않는다(엔진은 lease를 `failed`로 기록).
4. **결정이 창을 넘겨 도착하면 실패 처리.** Tool 호출이 창을 초과해도 결과 기록 전에 실패 처리.
5. **호스트가 총 상한을 원하면 opt-in.** `AgentExecutionBudget.max_total_seconds`(기본 `None`).
6. **유지되는 실제 한계:** step/tool/skill 개수, Tool별 `timeout_seconds`, 연결/읽기 타임아웃,
   durable lease fencing(`run_guard`)·heartbeat, 승인 유효기간, quota/비용, 사용자 취소(전파),
   보안 경계.
7. **단일 모델 호출 lane은 그대로.** `OrchestrationRunner`의 non-bridge 경로와
   `ContextualExecutionRunner`는 호출자가 선언한 `ExecutionContext.timeout_seconds`
   (기본 900, 최대 3,600)를 유지하며, 모델 transport의 600초 per-event read-idle이 실제 계약이다.
   새 20/45/60초 제한은 추가하지 않았다.

## 적용 지점

| 위치 | 변경 |
| --- | --- |
| `packages/padiem-ai-core/padiem_ai_core/agent_progress.py` | 신규: 진행 tracker + 유휴 watchdog await 헬퍼 |
| `packages/padiem-ai-core/padiem_ai_core/agent_definition.py` | `max_wall_seconds` = 유휴 창, `max_total_seconds` opt-in 상한 |
| `packages/padiem-ai-core/padiem_ai_core/agent_runtime.py` | 누적 차감 제거, 진행 시 창 재설정, 정지 시 fail-closed |
| `packages/padiem-ai-core/padiem_ai_core/agent_execution_bridge.py` | 공유 tracker 주입 |
| `packages/padiem-ai-core/padiem_ai_core/orchestration.py` | run/resume 브리지 2곳을 `await_with_agent_progress`로 교체 |

## 검증 (오프라인, fake-clock/단시간 실시간)

`packages/padiem-ai-core/tests/test_4194_agent_no_fixed_wall.py`

- 유휴 창(5초)보다 훨씬 긴 24초 진행 실행이 **완료**(기존 누적 예산이면 2단계에서 실패).
- 30초 정지 → `MAX_WALL_TIME`, `answer is None`(성공/재개로 표시되지 않음).
- step/tool 개수 예산, opt-in `max_total_seconds`, revoked `run_guard`(fencing/취소) fail-closed.
- `await_with_agent_progress`: 진행 시 창 유지, 정지 시 `AgentIdleTimeoutError`, 외부 취소 전파.
- 오케스트레이션 브리지: context 창(1.0초)보다 긴 1.5초 진행 실행 **완료**, 정지 실행은
  `orchestration_timeout`으로 실패하고 `RUN_COMPLETED` 이벤트 없음.
- `test_4194_model_lane_timeout_guard.py`는 "고정 cap 금지 + 모델 lane 600초 기본 유지"로 갱신.

## 남은 것 (이 PR 범위 밖)

- 운영 실모델/실 Worker 장시간 E2E와 재연결 상태 재조회, 취소의 HTTP 전달 경로
  (`/internal/v1/agent-skill/*`에 running run 상태/취소 표면 없음).
- `D1AgentRunLedger.quarantine_expired()`는 존재하지만 **호출자(scheduled trigger)가 없다** —
  worker가 죽은 stale `running` 행이 `needs_review`로 정리되지 않는다.
- 위 항목은 AI Platform QA [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318)에서
  구현 이후 검증/후속 구현으로 다룬다.
