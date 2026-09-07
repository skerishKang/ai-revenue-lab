# P01 Engine approval_continuation 활성화 진실 기록 v1 (WO-9 PR-A, #1966)

> 이 문서는 진실 기록이다. manifest flip을 포함하지 않는다.
> `approval_continuation` / `continuation/approval`은 본 PR 이후에도 DEFERRED를 유지한다.

## 1. 목적

- WO-9(#1966) continuation 활성화의 측정된 현재 상태를 기록한다.
- Production에 존재하는 것(SOURCE_PRESENT, PRODUCTION_STORE_BOUND)과
  존재하지 않는 것(BLOCKER_C1)을 분리해 기록한다.
- manifest flip은 본 문서·본 PR의 범위가 아니다(§5, §6).

## 2. SOURCE_PRESENT=YES

측정 근거 (base `08e914e5`):

- `apps/padiem-ai-engine/app/orchestration_service.py:726` `resume_payload` —
  서버 발급 continuation만 검증을 거쳐 resume.
- `apps/padiem-ai-engine/app/orchestration_service.py:983` `cancel_payload` —
  서버 발급 continuation만 cancel
  (원자적 claim_cancel / commit_cancel / release_cancel).
- `apps/padiem-ai-engine/app/orchestration_wire.py:29-30` —
  `ORCHESTRATE_RESUME_PATH=/internal/v1/orchestrate/resume`,
  `ORCHESTRATE_CANCEL_PATH=/internal/v1/orchestrate/cancel`.
- `apps/padiem-ai-engine/app/orchestration_wire.py:266-269` —
  `_parse_continuation_ref`: `cont_` prefix가 아니면 409 `invalid_continuation`.
- `apps/padiem-ai-engine/app/continuation_d1.py` —
  resolve / claim / commit / release / cancel+atomic D1 구현.
  미발급 ref는 409 "Continuation reference is invalid."
- `apps/padiem-ai-engine/app/approval_verifier.py` — approval 검증.
- `apps/padiem-ai-engine/migrations/0002_engine_continuations.sql` —
  `padiem_engine_continuations` 테이블.
- health capabilities `orchestration_resume` / `orchestration_cancel` = `available`
  (`app/contract_manifest.py:165-166`; A10 S0에서 런타임 단언).

## 3. PRODUCTION_STORE_BOUND=YES

측정 근거:

- `apps/padiem-ai-engine/wrangler.toml:21-24` —
  `[[d1_databases]] binding="ENGINE_CONTINUATION"`,
  `database_id="6b77ad02-bc27-488f-bb97-6325f6750cba"` (`padiem-engine`).
- `apps/padiem-ai-engine/worker_identity.py:56-69` —
  `_continuation_store_for_env`: 명시적 D1 authority만 사용하며,
  바인딩이 없으면 None을 반환 (Production 상태를 위조하지 않음).
- store가 명시적이지 않으면 resume/cancel은
  503 `continuation_store_unavailable`으로 fail closed
  (`app/orchestration_service.py:744-749`, `:993-998`).
- A10 S1/S2는 503이 아닌 409를 요구하므로,
  PASS는 곧 STORE_BOUND=PASS의 증거다.

## 4. BLOCKER_C1_NO_PRODUCTION_PAUSE_PRODUCER=OPEN

WO-10 PR-B: production composition now injects tool_binding_resolver from connector_bindings; resolver is None until a Gmail port/grant store is bound (PR-C). BLOCKER_C1 stays OPEN.

측정 근거:

- `apps/padiem-ai-engine/worker_identity.py:120,179` —
  Production composition이
  `tool_execution=ToolExecutionEngineService(tool_binding_resolver=None)` 주입.
- `apps/padiem-ai-engine/app/orchestration_service.py:249` (기본값 None),
  `:284-287` — resolver가 None이면 `_resolve_tool_binding`은 None 반환.
- `apps/padiem-ai-engine/app/orchestration_service.py:364-384` —
  서버 바인딩 없이는 tool authority를 전혀 부착하지 않으며,
  plan은 tool을 실행할 수 없음.
- `packages/padiem-ai-core/padiem_ai_core/orchestration.py:942-948` —
  plan bridge(`use_plan_bridge`)는 주입된 `tool_runtime`을 요구.
- 결론: Production에서 approval pause를 생성할 수 있는 경로가 없으므로,
  실제 pause → resume은 절대 발생할 수 없다. BLOCKER_C1=OPEN.

## 5. MANIFEST_STATE=DEFERRED (의도적)

- `apps/padiem-ai-engine/app/contract_manifest.py:172` —
  `approval_continuation` = DEFERRED (값 변경 없음, WO-9 주석만 추가).
- `apps/padiem-ai-engine/app/capability_manifest.py:403-405` —
  `continuation/approval` = DEFERRED (변경 없음).
- 유지 사유: store와 코드는 Production에 있으나 pause 생산자가 없으므로,
  활성화 주장(AVAILABLE)은 거짓이 된다. DEFERRED는 의도적이며,
  A10 PASS와 모순되지 않는다 (A10은 fail-closed + store-bound만 증명).

## 6. FLIP_CONDITION

다음이 모두 충족될 때 별도 PR에서 flip을 검토한다:

1. #2010 첫 커넥터 바인딩 — A3 실제 resolver가 Production composition에 주입됨.
2. 실제 Production pause → resume 1건 입증 (A10 PASS + 실측 로그).
3. 별도 PR (본 PR-A에는 flip을 포함하지 않음).

## 7. EVIDENCE

- 게이트 실행 (main `554d678ec300151d09557d7fdf2bb14acafaf9a1` = WO-9 PR-A 머지 후 첫 main,
  2026-09-07, conclusion=success):
  https://github.com/skerishKang/ai-revenue-lab/actions/runs/34085054608
- A10 PASS 라인 원문 (Production 게이트 로그):
  `A10_CONTINUATION_SMOKE=PASS REAL_PROVIDER_CALLS=0 ROWS_WRITTEN=0 STORE_BOUND=PASS FAIL_CLOSED_RESUME=PASS FAIL_CLOSED_CANCEL=PASS CROSS_APP=PASS BLOCKER_C1=OPEN`
- A9 PASS 라인 원문 (동일 게이트 실행):
  `A9_SMOKE=PASS REAL_PROVIDER_CALLS=1 ROWS_WRITTEN=1 BLOCKER_4=PASS BLOCKER_5=PASS BLOCKER_6=PASS BLOCKER_7=PASS`
- 배포/스모크 게이트 표식: `B54_ENGINE_PRODUCTION_DEPLOY=PASS`,
  `B54_ENGINE_PRODUCTION_SMOKE=PASS`
- 계약 테스트: `.github/tests/test_b54_engine_deploy_gate_smoke.py`
  (gate-contract CI, 정적 파싱만 수행, Production 호출 없음)
