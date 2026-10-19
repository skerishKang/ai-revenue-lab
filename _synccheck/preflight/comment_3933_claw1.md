## CLAW1 — B54 trusted first-turn P01 context: exact call graph + source-backed blocker (2026-10-13 KST)

```text
WORKER=CLAW1
ISSUES=#3933,#3936
MAIN_SHA=5179a7c7df4dcfc1e17b2a35e8de547292b6c013
SCOPE=B54_TRUSTED_FIRST_TURN_P01_CONTEXT
EXISTING_CP_ISSUER=PRESENT_SERVER_RESOLVED_PRODUCT_PINNED
FIRST_TURN_DURABLE_RESERVATION=MISSING
PRIVATE_TYPED_HANDOFF=MISSING_ENGINE_ADMISSION_IS_A_CLOSED_SET
OFF_BY_DEFAULT=YES_NO_SOURCE_CHANGE
NEGATIVE_TESTS=NO_NEW_TESTS_4538_REUSED_NOT_DUPLICATED
PR_DRAFT=NONE
EXACT_HEAD_CI_GITGUARDIAN=NOT_APPLICABLE_NO_DIFF
COLLISION_4373=NONE
PROVIDER_POST=0
B14_GO_MODELS=OFF
PRODUCTION_MUTATION=0
NEXT=STOP_SOURCE_BLOCKER
```

`FINAL=SOURCE_GAP_CONFIRMED / IMPLEMENTATION_BLOCKED`. 3번 조건(기존 canonical 저장소 + 인증된 내부 전송이 이 슬라이스를 **안전하게** 지지할 것)이 성립하지 않아 소스 변경과 Draft PR을 만들지 않았습니다. 아래는 정확 SHA 소스 근거와 최소 설계안입니다.

### 1. 정확 호출 그래프 — 첫 턴(`conversation_id=None`) vs 기존 검증 대화

진입: `apps/padiem-chat/app/claw_general_routes.py::claw_general_execute`

| 단계 | 첫 턴 | 기존 대화 |
|---|---|---|
| 대화 참조 해석 | `_resolve_intake_session_reference`(`claw_routes.py:332`)에 `conversation_id=None` → `(None, None)` 즉시 반환 (`:341`) | body의 **단일 필드** `conversation_id` → `validate_conversation_id` shape 검사 → `HistoryStore.get_conversation(uid, cid)` 소유자 재검증. 실패 시 400/401/404/503, **쿼터·P01 이전** |
| 문맥 | `_owner_claw_context(request, None, latest)` → `latest` 그대로 (`claw_general_routes.py:216-219`) | `get_conversation_model_context` full 원문 → **텍스트로만** `intent.task`에 합성 |
| CP 세션 | `subject_identity_lane=True`이면 `resolve_current_b54_canonical_session` **동일하게 호출됨** (`:494-506`) → `subject_id` 확보 | 동일 |
| tenant | `tenant_id`를 읽기만 함(`:507`), **요구하지 않음** | `if conversation_id is not None:`(`:508`)에서 비었으면 403 `workspace_scope_unavailable` |
| P01 전송 | `_trusted_p01_request_snapshot`(kagent) closed shape, 유일한 신원 필드 `session_id = run.run_id` | 동일 |
| 지속 대화 | **디스패치 전 없음.** 완료 후 `_save_claw_exchange` → `history.py::append_exchange`가 `_chat_id()`로 발급(`history.py:855-859`) | 기존 row 재사용 |

즉 첫 턴은 **subject만 검증**되고 tenant는 미요구이며, 디스패치 시점에 대화를 가리키는 지속 가능한 참조가 **존재하지 않습니다**. 브라우저로 나가는 `conversation_id`는 완료 **후** 발급됩니다. #4538이 고정한 seam과 일치하며, 중복 단언은 추가하지 않았습니다.

### 2. 기존 권위로 "디스패치 전 서버 발급 대화 예약"이 가능한가 → **불가**

- **`conversations` 테이블에 tenant/subject 컬럼이 없습니다.** `migrations/001_auth_history.sql`: `id, user_id, title, created_at, updated_at`. 이후 유일한 변경은 `002_projects.sql`의 `project_id` 추가. tenant는 `claw_run_history.workspace_id`(`015`)로 **run에만** 붙습니다. 따라서 "owner+tenant-bound durable conversation reference"는 **기존 스키마로 표현 불가**합니다.
- **pre-dispatch 예약 프리미티브가 없습니다.** `INSERT INTO conversations`는 소스 전체에서 두 곳뿐입니다.
  - `history.py:857` — `append_exchange`. `creating`일 때만 발급하며 **완료된 assistant 응답과 같은 트랜잭션**에서 row를 만듭니다(부분/빈 대화를 남기지 않으려는 의도적 설계, `:854-856` 주석).
  - `history.py:894` — `create_web_xlsx_p01_run`. 실제로 **디스패치 전** owner+workspace 대화/run을 만드는 유일한 예이지만, `filename`이 `.xlsx`여야 하고 title·`channel="web"`·`action="xlsx_p01"`·`status="running"`으로 **XLSX 승인 워크플로 전용**입니다.
- **재사용 후보는 전부 탈락합니다.**
  - `claw_artifact_delivery_receipts`(`036`)의 `INSERT OR IGNORE … SELECT` 예약은 `conversations c INNER JOIN claw_run_history r … AND r.status='completed'`를 요구 → **run 완료 후** 중복 전송 방지용입니다.
  - `claw_approval_handoff`(`016`)는 `run_id`·Engine 발급 `pause_id`/`pause_expires_at`이 있어야 하며 resume 문맥 저장소입니다(마이그레이션 주석이 스스로 "Engine continuation store가 아니다"라고 명시).
  - `dispatch_quota.py`의 reservation은 프로세스 로컬 ContextVar 버킷으로 **대화·tenant 신원도, 지속 만료도 없습니다.**
- **발급/만료/replay 저장소가 없습니다.** 만료 컬럼을 가진 지속 테이블은 `006 orchestration_continuations`(Engine continuation), `007 identity_shadow`, `008 claw_document_metadata`, `016 claw_approval_handoff`, `029/030/034 claw_web_xlsx_*`뿐이며, 어느 것도 디스패치 전 대화를 product+owner+tenant 범위로 결박하지 못합니다.

### 3. 인증된 내부 전송도 typed 비공개 컨텍스트를 지금 받지 못합니다

- Engine 입장 계약은 **닫힌 집합**입니다: `apps/padiem-ai-engine/app/orchestration_identity_service.py:41-53` `_ORCHESTRATE_ALLOWED_FIELDS`, 미지 필드는 `_reject_unknown_fields` → **400 `unsupported_orchestration_field`**.
- Snapshot도 닫힌 shape입니다(`kagent/p01_adapter.py::_trusted_p01_request_snapshot`, `:254`)이며 identity 필드는 `session_id = run.run_id` 하나뿐입니다.
- 따라서 `B54VerifiedCodingContextV1`을 Engine까지 전달하려면 **Engine 입장 allowlist를 함께 바꾸는 cross-service 계약 변경**이 필요합니다(=CENTRAL 리뷰 대상이자 "새 마이그레이션/자격/정책" 조건).

### 4. 최소 설계안 (제안 — 미실행, CENTRAL 승인 필요)

1. **저장(추가 전용 마이그레이션 1건, 번호는 040 충돌 회피로 다음 빈 번호):** `claw_coding_conversation_grant(id PK=검증된 chat_ id, user_id, subject_id, tenant_id, product_id, route_scope, issued_at, expires_at, state∈reserved/active/revoked, correlation_key, UNIQUE(user_id, correlation_key))`. 기존 `conversations`/`claw_run_history` 권위는 그대로 두고 **새 대화 권위를 만들지 않습니다**(예약 레코드일 뿐).
2. **B54 producer(기본 OFF):** `Settings` 플래그 하나(기본 False). ON일 때만 첫 턴에 (a) canonical subject **및 비어 있지 않은 tenant** 필수 → 없으면 쿼터/P01 이전 403, (b) 쿼터 이전에 `(user_id, correlation_key)` 기준 `INSERT … ON CONFLICT DO NOTHING`로 예약하고 발급된 `chat_` id를 반환, (c) 디스패치 전 중단 시 `state='reserved'`·N초 경과분만 owner-scope로 정리(고아 노출 0).
3. **typed projection:** `B54VerifiedCodingContextV1`(version, issuer, product, subject, tenant, conversation ref, route scope, issued_at, expires_at, correlation) — **내부 Service Binding 홉 전용**, 공개 응답 envelope 미확장.
4. **Engine 입장 확장:** reviewed 필드 1개만 allowlist에 추가 + issuer/product/scope/expiry/correlation 엄격 검증. B14 내부 `session_id`는 **검증된 대화 ref에서만** 파생. B66/B62 일반 chat은 B54 coding scope를 빌릴 수 없습니다.
5. **구현 시 테스트:** 첫 턴 subject/tenant 부재(pre-quota, provider POST 0), foreign/expired/revoked 대화, owner A/B, tenant A/B, 위조 body 필드·헤더, 동일 `correlation_key` replay → 기존 예약 반환·2차 디스패치 0, 중단 예약 정리, SSE·completed 동등. #4538이 이미 만족한 단언은 재작성하지 않습니다.

### 5. 안전 경계

`PROVIDER_POST=0`, `PRODUCTION_MUTATION=0`(Cloudflare/D1/Worker/Secret 무변경), `B14_GO_MODELS=OFF`, `#4373` 파일(`claw_web_xlsx_p01_*`, `web_xlsx_p01_engine_client.py`, `web_xlsx_p01_refusal.py` + 테스트/문서)과 **접촉 0**. 인증·DB 변경은 하지 않았습니다. #3936 LIVE 검증은 계속 OPEN입니다.

`NEXT=CENTRAL_REVIEW` — 위 1~4 설계안(특히 신규 마이그레이션 1건과 Engine 입장 allowlist 확장)을 승인해 주시면 그때 최소 슬라이스와 회귀 테스트를 Draft PR로 올리겠습니다.
