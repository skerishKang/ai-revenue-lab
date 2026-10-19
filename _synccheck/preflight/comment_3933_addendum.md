### 보강 — 지시 2번의 "같은 B54 제품 + canonical subject + tenant/workspace, revoke/만료 가드" 증명

앞 보고에서 제품·subject·tenant 결박은 인용했으나 **revoke/만료 가드**를 별도로 명시하지 않아 보강합니다(변경 없음, 읽기 전용).

**현재 존재하는 가드 (정확 SHA `5179a7c7` 소스)**

| 가드 | 위치 | 동작 |
|---|---|---|
| B54 제품 고정 | `b54_canonical_session.py::resolve_current_b54_canonical_session` | 요청에서 읽는 값은 서명 쿠키의 product user id **하나뿐**이고 `product_id`는 Control Plane 브리지 안에서 `b54-padiem-claw`로 고정 → B62 세션 재사용 불가 |
| 세션 만료 | `b54_canonical_session.py::B54CanonicalSessionProducer.establish` | 만료는 서버 시계 + `Settings.session_max_age_seconds`로만 계산(`expires_at = authenticated_at + max_age`), 호출자가 연장·소급 불가 |
| revoke/expiry/부재 fail-closed | 같은 모듈 `:resolve_current_b54_canonical_session` | `signed out`, CP private binding 부재, **활성 B54 세션 없음**이면 `None` 반환 → 라우트가 403 `canonical_b54_session_unavailable` |
| 새로고침 세션 계약 | `claw_routes.py::_resolve_canonical_tenant`(`:291`) | `resolve_refreshed_session` 계약(session id, chat product, USER subject, canonical subject, monotonic revision, **ACTIVE effective state**, snapshot type) 중 하나라도 위반(revoked/expired/product·subject 불일치/revision 역행)이면 `None` → 호출부 fail-closed |
| tenant 출처 | `claw_general_routes.py:507` | `tenant_id`는 CP `AuthSessionSnapshot`에서만 읽음. body의 `tenant_id`/`workspace_id`/`subject_id`/`user_id`는 P01 run에 도달하지 않음(#4538로 이미 고정) |
| run/대화 결박 | `claw_general_run_history.py::project_completed_general_run` | 비-null `conversation_id`는 기록 직전 **다시** `validate_conversation_id` + owner 조회를 통과해야 함 |

**없는 가드 (blocker의 일부)**

- 첫 턴에 결박할 대상이 없으므로 **"이 첫 턴 부여의 revoke/만료"** 라는 개념 자체가 존재하지 않습니다. 즉 오늘 첫 턴은 (a) tenant 미요구, (b) 만료되는 부여 없음, (c) replay 판정할 correlation 저장 없음입니다. 새 승인 시 이 세 가지를 함께 설계해야 하며, 이는 앞 보고의 최소 설계안 1~3번과 동일합니다.
