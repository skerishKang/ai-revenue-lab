# #4194 — Agent/Task 영속 실행 Lease·체크포인트 1단계 구현 (2026-10-11 KST)

## 완성 범위와 제한

이번 변경은 **Core 실행 경계에 선택적으로 연결 가능한 영속 실행 통제 기초**다. **Cloudflare 운영 Agent의 자동 재개·백그라운드 실행 전체 기능이 완성됐다는 의미가 아니다.** 기존 실행 상한(Agent 900~3600초)과 B14 모델 응답 유휴 감시(기본 600초)를 변경하지 않는다.

- `padiem_ai_core.agent_durable_lease.SQLiteAgentDurableRunLedger`: 프로세스 종료 후 재열어도 남는 host-private SQLite 영속 레코드. 신뢰한 서버가 발급한 `run_id + owner_scope + request_fingerprint`에만 종속된다. 프롬프트, 비밀번호, 모델 답변, Tool 인자, 고객 문서 bytes는 저장하지 않는다.
- 신규 작업 start는 **이미 있는 run_id 재생성·중복 시작을 거부**한다. 임대 세대(epoch)·실행 worker ref·기한(1~3600초)으로 fencing.
- `heartbeat`: 기한 내·현재 세대·정확한 소유 범위에서만 연장. 만료 임대와 옛 executor의 쓰기·완료 처리 거부.
- `execution_guard`: `AgentPlanExecutor.execute(run_guard=ledger.execution_guard(lease))`로 **명시적으로 opt-in**할 수 있다. `BoundedAgentRuntime`은 step 이전·Tool 호출 이전·결과 수용 이전·완료 직전에 guard 검사. 최초 검사 시 `side_effect_uncertain=1`을 동일 트랜잭션에 기록해, 진행 중 pre-work pause/reclaim 경쟁을 차단한다.
- `checkpoint`: 단조 증가하는 step 번호 **메타데이터**만 기록. 모델 호출비용/외부 side effect 가능성을 기본적으로 unknown으로 기록하고 재실행 가능 상태로 자동 승격하지 않는다. Tool 결과·승인 토큰을 대신 보관하거나 암호화 없이 persisted context를 저장하지 않는다.
- `pause_before_work` + `resume_prework`: **step=0, 아직 실행 시작 전** 상태에 한해 원자적으로 새로운 epoch/worker를 발급하고 이전 작업자 무효화. 이미 실행된 step·Tool은 자동 재개하지 않음.
- `cancel`: 인증된 소유 범위와 exact fingerprint에 한해 영속 취소 상태 기록·임대 세대 증가. 진행 중 async task 자체의 즉시 취소는 host가 별도로 signal해야 하며, 비가역 Tool이 이미 실행되었으면 되돌리지 않는다.
- `quarantine_expired`: 비정상 종료·heartbeat 유실 상태를 `needs_review`로 격리하고 **자동 재실행하지 않음**. 별도의 신뢰할 수 있는 side-effect 재조정 필요.
- `finish`: 미만료, 현재 fencing 소유자에 한해 종료 상태 기록. 기존 승인·Tool 권한·비용 정책을 대체하지 않는다.

### 호출자 예시 (검증된 서버 코드에서만; 사용자 입력을 신뢰하지 말 것)

```python
# SQLite host-private persistence ONLY (no use in Cloudflare Python Worker).
ledger = SQLiteAgentDurableRunLedger(database_path=trusted_host_private_db)
lease = ledger.start(
    run_id=server_minted_run_id,
    owner_scope=server_authenticated_owner_scope,
    request_fingerprint=server_canonical_request_sha256,
    worker_id=server_worker_id,
)
# In a trusted host coroutine: heartbeat lease while actively executing.
result = await agent_plan_executor.execute(
    # normal approved plan + authorization arguments unchanged,
    run_id=lease.run_id,
    run_guard=ledger.execution_guard(lease),
)
# Commit result to the app-owned authoritative store and call finish(lease,..)
# ONLY after verifying active fencing epoch. Any tool/inference may be non-idempotent.
```

`AgentRunLease`는 인증 수단이 **아니다**. 호출 호스트가 `owner_scope`를 로그인 세션으로부터 검증하고 인가된 plan/Tool을 적용해야 한다. DB 디렉터리는 서버 내부의 권한이 제한된 지속 디스크여야 한다. 원본 SQL/행 및 epoch 값을 브라우저에 노출하지 않는다. `execution_guard`는 외부 제공업체·Tool 트랜잭션 자체와 원자적으로 묶이지 않으므로, Tool에는 **별도의 request idempotency/승인 및 실제 side effect 검증**이 계속 필요하다.

## 집중 검증

```text
TEST_SUITE = test_agent_durable_lease + test_agent_execution_bridge
           + test_agent_runtime + test_approval_pause_semantics
TESTS = 42 PASS, 0 FAIL (Windows package-local offline)
ORIGINAL_RUNNER_WALL_CLOCK_REMOVED = NO
POST_TOOL_AUTO_RESUME = NO
PRODUCTION_DURABLE_ADAPTER = NOT_CONNECTED
PROVIDER_POST = 0
SECRETS_DB_PRODUCTION_MUTATION = 0
```

검증 항목: reopen 후 영속성, duplicate run 거부, 다른 소유자 비노출, 만료 기한 정밀 판정, heartbeat, 요청 fingerprint mismatch, pre-work 1회 재개와 이전 epoch 차단, Tool 시작 이후 pre-work 재개 금지, 취소 후 Tool 실행 거부, Tool 도중 취소시 추가 dispatch 거부, 승인 경계 기존 회귀.

## #4194 종료 전 남은 핵심

1. **운영 Cloudflare D1에 적용 가능한 원자적 상태/lease 저장소와 별도 긴 작업 실행기**를 구현. Python Workers 로컬 `sqlite3`를 운영 영속 저장소로 착각하거나 이 모듈을 즉시 Production에 활성화하지 않는다.
2. 실행 중 주기적 heartbeat 및 host cancellation signal/timeout-after-progress, 트랜잭션 내 Tool dispatch fence, provider cost/idempotency 보호, durable checkpoint에 필요한 **검증 가능한 전체 step/tool result context**와 안전한 보관/복원 계약.
3. 승인 일시정지와 동일한 Trusted Agent/Tool 권한으로 **실제 post-tool 재개** 구현. lease 만료 후 이전 Tool이 실행됐을 수 있으면 후속 Tool 재시도는 수동 reconcile 전 금지.
4. synthetic 원본/도구만으로 다중 worker 경합, 프로세스 재시작, failure/cancel/restart, 타계정 차단 E2E; 정확한 HEAD CI, 실제 Production release의 binding·rollback·운영 경로 readback.
5. 별도 직접 모델 호출 제품·실제 활성 Worker의 B14 모델 600초 실효설정 전수 인증. 필요 없는 실유료/사용자 금지 모델 반복 실험 금지.

**판정:** 이 PR은 위험한 장시간 wall 제한을 임의로 끄지 않고 **실제로 필요한 durable control plane 기반**을 제공한 구현 마일스톤. #4194 OPEN 유지.
