# PADIEM Connector S1 — 서버 등록 계약 (LOCAL1 → LOCAL2 핸드오프)

**Issues:** #4139 (구현) · #4438 (PR) · #3099 (통합 검증)
**Contract module:** `packages/padiem-control-plane/padiem_control_plane/padiem_connector_enrollment.py`
**Canonical pairing authority:** `packages/padiem-control-plane/padiem_control_plane/local_agent_broker_pairing.py`
**Status:** 서버 계약 완료 · **등록 활성화 OFF** (`PRODUCTION_ACTIVATION=False`) · Draft 유지 · Windows live E2E 미수행

---

## 0. 절대 원칙 (Connector가 지켜야 할 것)

1. **기존 Canonical 인증 세션만 사용한다.** Connector는 PADIEM 계정의 아이디/비밀번호를 **보유·전송하지 않는다**. 브라우저 쿠키를 Connector로 넘기지 않는다. 등록 시작은 **이미 로그인된 정규 세션** 위에서 이루어진다.
2. **서버가 owner/workspace를 부여한다.** `account_ref` / `workspace_ref` / `owner_subject_id`는 서버가 인증 세션에서 도출한다. Connector·브라우저·제품 라우트가 이 값을 supplied 하는 경로는 존재하지 않는다.
3. **브라우저의 주장은 증거가 아니다.** `consent_valid=true` 같은 플래그는 어떤 경로로도 신뢰되지 않는다. 동의 활성 상태는 서버 소유 내구 레코드에서 재조회한다.
4. **등록 동의 ≠ P01 READ/WRITE 승인.** PC 등록 동의는 파일 읽기/쓰기/실행 권한을 부여하지 않는다. 실행 승인은 기존 P01 경로가 별도로 소유한다.

---

## 1. 등록 시작 (엔드포인트 · 인증)

| 항목 | 내용 |
| --- | --- |
| 진입점 | `issue_connector_enrollment_challenge(...)` (Control Plane 서버 측 통합 함수) |
| 선행 조건 | 정규 로그인으로 발급된 **canonical auth session** (`AuthSessionSnapshot`, state=`ACTIVE`, subject_type=`USER`, tenant 존재, 검토된 product) |
| 입력 | `auth_session`, `allowed_product_ids`, `scope_resolver`(서버 주입 owner resolver), `consent`, `device_id`, `pairing_authority`, `consent_liveness_authority`, `now`, `ttl_seconds` |
| 서버 동작 | ① 세션 활성·주체·tenant·product 검증 → ② owner resolver로 **서버 도출** account/workspace scope → ③ 동의(스코프·PC 일치·활성) 검증 → ④ **동의 내구 레코드 재조회(liveness)** → ⑤ canonical pairing authority의 `issue_enrollment_challenge` 호출(서버 소유 바인딩 기록) |
| 출력 | `ConnectorEnrollmentChallengeReceipt`: `challenge`(challenge_id/account/workspace/issued_at/expires_at), `pairing_code`(1회성 자격증명), `scope`, `consent_id`, `device_id`. `safe_dict()`에 코드 미포함 |

- `pairing_code`는 **한 번만** 반환되는 자격증명이다. 로그·영속 저장 금지.
- Challenge TTL: 기본 300초(최대 600초, 최소 30초). 만료 시 `pairing_challenge_expired`.

## 2. 소유 증명 (PC ID · possession proof)

- 소유권 = one-time code의 **소유(posssession)**. self-asserted device id는 증거가 아니다.
- proof = `pairing_proof_ref(challenge_id, device_id, pairing_code)` — HMAC-SHA256 transcript.
- proof가 잘못되면 `invalid_pairing_proof` / `enrollment_proof_invalid`(텍스트 미echo).

## 3. 상환 (redemption) 계약

`redeem_connector_enrollment(...)`는 **단 하나의 mutating 호출** 전에 아래를 전부 재검증한다:

1. 인증 세션 재검증(발급 후 세션이 철회되면 거부 — `canonical_session_inactive`)
2. 동의 재검증: 활성 상태·스코프·컴퓨터 일치(제시 객체 + **내구 레코드 재조회**)
3. 서버 소유 바인딩 probe(비mutating): challenge_id → (consent_id, owner, account/workspace, device_id) 정확 일치
   - 불일치: `enrollment_consent_swap_denied` / `enrollment_device_swap_denied` / `enrollment_binding_owner_mismatch` / `enrollment_binding_scope_mismatch`
4. 단일 사용·만료 검사

**성공 시 출력** `ConnectorEnrollmentReceipt`:

| 필드 | 의미 |
| --- | --- |
| `binding_ref` | canonical Broker 바인딩 참조(`pairing-binding.<digest>`) |
| `device_id` | 등록된 PC ID(서버 소유) |
| `account_ref` / `workspace_ref` | 서버 도출 스코프 |
| `credential` | **1회 반환** 디바이스 자격증명(bytes). Connector는 안전하게 보관 |
| `credential_generation` / `credential_expires_at` | 회전 세대·만료 |
| `consent_id` | 등록에 사용된 동의(감사 추적) |

- 중복 등록(같은 PC의 활성 바인딩 존재): canonical Broker가 `duplicate_device_binding` → `enrollment_duplicate_device_denied`. **같은 PC의 재등록은 먼저 revoke** 후에만 가능.
- 클라이언트가 supply한 receipt는 어떤 경로로도 수용되지 않는다(서명된 receipt는 `not implemented`, 권위는 서버 소유 바인딩).

## 4. 동의(Consent) 모델

- **PC 1대당 1개 동의.** `ConnectorEnrollmentConsent(consent_id, owner_subject_id, account_ref, workspace_ref, device_id, granted_at, withdrawn_at)`. 두 번째 PC는 명시적 두 번째 동의가 필요.
- 동의는 **server-owned 내구 레코드**에서 발급·철회된다. 현재 `CONSENT_LIVENESS_AUTHORITY`(`server_trusted_enrollment_consent_authority`)는 **미배선**이며, 배선 전까지 등록은 기본 거부(`consent_liveness_authority_implemented=False`).
- 서버 배선 계약(`CanonicalConsentLivenessPort`):

  ```python
  def current_consent(self, *, consent_id: str, now: datetime) -> ConnectorEnrollmentConsent | None
  ```

  - issue 시점과 redeem 시점 **각각** 호출된다(내구 레코드 재조회).
  - 미배선/레코드 없음 → `enrollment_consent_liveness_dependency_unmet`
  - 레코드 불일치 → `enrollment_consent_scope_mismatch`
  - 레코드 비활성(철회·미개시) → `enrollment_consent_withdrawn`
- 이 포트는 **서버 와이어링 의존성**이다. 브라우저/Connector 입력값으로 대체 불가(불리언 오버라이드는 제거됨).

## 5. Broker 바인딩 · 연결 상태

- 등록 완료 = canonical Broker(`InMemoryLocalAgentBrokerAuthority` / state-backed)에 `register_binding` 1건. **두 번째 기기 DB 없음.**
- 연결·heartbeat·세션·명령 상태는 canonical Broker RPC/프로젝션(`local_agent_broker_rpc`, `local_agent_pc_access`, kagent server projection)이 소유한다. 이 계약은 등록 사실만 생산한다.
- 자격증명 회전/철회: canonical Broker의 `rotate_credential` / `revoke_binding`. 철회된 바인딩은 인증 불가(`device_binding_revoked`).
- 오프라인·자격증명 만료·철회는 모두 fail-closed.

## 6. 실패 코드와 복구

| 코드 | 의미 | 복구 |
| --- | --- | --- |
| `canonical_session_required` / `canonical_session_inactive` | 세션 없음/비활성 | 정규 로그인 재수행 |
| `enrollment_consent_device_mismatch` | 동의가 다른 PC | 해당 PC의 명시적 동의로 재발급 |
| `enrollment_challenge_expired` | TTL 만료 | 새 챌린지 발급(재시도 안 함 — 새 요청) |
| `enrollment_duplicate_redeem_denied` | 1회성 코드 재사용 | 새 챌린지 발급 |
| `enrollment_proof_invalid` | proof 불일치 | code/proof 재계산(자동 재시도 금지) |
| `enrollment_consent_swap_denied` | 발급 동의 ≠ 제시 동의 | 원발급 동의로 상환 |
| `enrollment_consent_withdrawn` | 내구 레코드 비활성 | 소유자 재동의 후 재발급 |
| `enrollment_consent_liveness_dependency_unmet` | liveness 권한 미배선/레코드 없음 | 운영 배선 후 재시도(현재 기본 상태) |
| `enrollment_duplicate_device_denied` | 같은 PC 활성 바인딩 존재 | revoke 후 재등록 |
| `enrollment_scoped_redemption_required` | enrollment 챌린지를 generic 경로로 상환 시도 | `redeem_enrollment` 경로 사용 |
| `enrollment_dependency_unavailable` | pairing authority 미지원 | 서버 배선 확인 |

모든 거부는 **bounded reason code**만 반환한다. canonical 업스트림 텍스트는 echo되지 않는다.

## 7. 테스트·검증 상태

- `tests/test_padiem_connector_enrollment.py`: 52 tests (S1-01…S1-52)
- `tests/test_local_agent_broker_pairing.py`: authority-level guard 포함
- Control Plane 전체: 1189 passed
- Windows Connector(`apps/claw-connect/**`, LOCAL2)는 본 PR 범위 밖 — **미수정**.

## 8. 활성화 게이트 (CENTRAL CTO)

등록 활성화는 다음이 모두 충족되기 전 **OFF** 유지:

1. `CanonicalConsentLivenessPort`의 durable 서버 구현 배선(Control Plane 권한기관 통합)
2. 제품 라우트(서버 핸들러)가 세션→issue/redeem을 노출 (불리언 오버라이드 노출 금지)
3. 신규 synthetic PC로 one-shot live E2E (LOCAL2 Connector + 실제 로그인 세션)
4. CENTRAL CTO 승인
