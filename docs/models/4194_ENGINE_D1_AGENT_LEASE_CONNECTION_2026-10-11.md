# #4194 — Engine Agent/Skill ↔ Cloudflare D1 영속 Lease 연결 (2026-10-11)

## 소스 연결 범위 (운영 비활성)

이번 변경은 기존 [Core Agent lease 모듈](../../packages/padiem-ai-core/padiem_ai_core/agent_durable_lease.py)의 **fencing/guard 계약**을, 실제 Engine `AgentSkillEngineService.run_payload` 및 Core `OrchestrationRunner` → `AgentPlanExecutor` → `BoundedAgentRuntime` 경로에 연결한다. **코드 병합만으로 Cloudflare D1 운영 기능을 활성화하지 않는다.**

- 신규 Engine `app/agent_durable_d1.py`: 기존 `ENGINE_CONTINUATION` D1 바인딩(동일 `padiem-engine` DB)을 사용하는 비동기 단일행 원자성 SQLite/D1 SQL. 서버 파생 `app_id + subject_id` 해시 스코프, 동일 요청의 canonical SHA256, 서버 난수 run/worker ID, epoch fencing, heartbeats, 취소, step 번호의 단조증가 checkpoint, 만료 시 `needs_review` 격리. 고객 프롬프트·Tool 인자·API 키·응답 원문 미저장.
- `migrations/0011_engine_agent_durable_runs.sql`: 운영 DB **별도 provision gate 대상**. Worker 런타임에서 `CREATE TABLE` 없음.
- `worker_identity._agent_skill_service_for_env`: 배포 소유자가 **정확히** `PADIEM_ENGINE_AGENT_DURABLE_ENABLED=true`를 설정할 때에만 기존 `ENGINE_CONTINUATION`의 D1 어댑터를 공급. flag 없음/false에서는 기존 Agent/Skill 서비스 경로를 동일하게 사용. true인데 D1 바인딩이 없으면 503 fail-closed. Migration 미실행 시 첫 D1 요청 실패 -> 503, Tool dispatch 0.
- Engine의 이미 인증된 `EngineAgentSkillBinding` → `wire.selection.subject_id`만으로 스코프 결정. 외부 JSON에서 app/subject/worker/lease/epoch를 임의 지정하거나 D1 레코드를 직접 실행할 수 없음. `run_id`를 서버에서 만든 후 Core bridge에 주입.
- Core의 `agent_run_guard`/비동기 guard와 `agent_checkpoint_hook`: 첫/각 Step, Tool 실행 전, Tool 결과 수용 전, 종료 전 D1 lease 유효성 확인. Guard의 첫 원자 UPDATE로 불확실한 외부 부작용 시작 기록. Tool 완료 후 checkpoint step 번호를 같은 D1에서 보존. D1 실패·취소·만료·옛 epoch면 이후 실행 중지. API 호출 중 즉시 취소와 원격 side effect rollback은 별도 기능이며 이 보호만으로 제공하지 않는다.
- Engine은 실행이 살아 있는 동안 독립 heartbeat task(30초 간격, lease 120초)를 유지하고 실행 후 명시 종료. 재시작 시 **이미 Tool을 실행한 작업 자동 재실행 금지**; step=0 pre-work만 별도 ledger 메서드에서 재개 허용.
- 이미 배포된 P01 일반 실행·Claw, AgentSkill 승인 재개/취소 API는 이 **신규 D1 가드의 적용 범위 밖**. Agent/Skill initial run에 한정. 향후 동일 fence·안전 checkpoint를 승인 재개·사용자 취소와 전체 Agent/Task 경로에 통합해야 함.

## 검증

- `tests/test_4194_agent_durable_d1.py`: 실제 SQLite 실행을 D1 `prepare().bind().run()/first()` 인터페이스로 제공하고 migration 0011을 적용. 영속성·중복 run 차단·다른 owner/fingerprint 비공개·epoch fencing·heartbeat/expiry·취소·post-tool 재개 거부·실제 trusted Agent/Skill tool execution → D1 완료+checkpoint·미적용 schema → 503/Tool 호출 0 확인.
- 기존 `test_agent_skill_service.py`와 Core `test_agent_durable_lease.py`, `test_agent_execution_bridge.py`, `test_agent_runtime.py`, `test_approval_pause_semantics.py` 회귀: **Engine 30/30 + Core 42/42 PASS** (Windows isolated PYTHONPATH). 정확한 HEAD CI는 PR에서 별도 확인.
- 테스트는 전부 합성 Tool이고 모델 B14/공급자 실 POST=0, R2/D1 Production 접근/변경=0, 시크릿 변경=0.

## 운영 활성화 전 별도 준비

1. 운영 `padiem-engine` D1에 0011 migration을 **승인된 스키마 변경 절차**로 적용하고 GET-only sqlite_schema readback. 기존 모든 테이블·바인딩·백업/rollback 범위 보존. 이 PR은 절대 자동 apply 안 함.
2. 활성 Engine Worker에서 기존 `ENGINE_CONTINUATION` D1 binding 이름과 DB id를 READ-ONLY 확인하고 신규 plain-text **오직 하나** `PADIEM_ENGINE_AGENT_DURABLE_ENABLED=true` enable. 기존 서비스/Secret binding 1:1 패리티 유지하고 배포 버전 readback.
3. 실제 authenticated AgentSkill initial run의 `run_id`, heartbeat, step checkpoint, cancel/stale-worker/expired 후 Tool 0, cross-subject 404/non-disclosure E2E 검증. 운영 고객/유료 Provider 사용 없이 QA synthetic.
4. Engine의 **일반 Orchestration/P01/Claw 경로**, 별도 AgentSkill resume/cancel 경로의 full-state checkpoint·승인/Tool side effect reconciliation, 자동 heartbeat 복구/외부 작업 취소, 전 제품 active runtime 600초 policy 검증이 완료되기 전 #4194는 OPEN.

**종합 판정:** `ENGINE_AGENTSKILL_D1_SOURCE_WIRING=IMPLEMENTED`; `D1_MIGRATION_SOURCE=READY_NOT_APPLIED`; `PRODUCTION_FLAG=OFF`; `LIVE_ENGINE_AGENT_RESUME=NOT_VERIFIED`; `ISSUE_4194=OPEN`. 기존 Agent 900~3600초 wall 제한은 안전한 포괄적 재개 기능을 구현하기 전까지 유지한다.
