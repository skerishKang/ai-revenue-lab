# PADIEM Connector S2 — 클라이언트 등록 계약 (LOCAL2 → CENTRAL 핸드오프)

**Issues:** #4139 (구현) · **PR:** #4463 (Draft, 미병합) · 상위 서버 계약: LOCAL1 PR #4438
**Client module:** `apps/claw-connect/claw_connect/enrollment.py`
**Server contract (read-only mirror):** `padiem.connector-enrollment.v1` (`padiem_connector_enrollment.py`, LOCAL1 소유 — 본 PR에서 수정하지 않음)
**Status:** 클라이언트 구현 완료 · **실제 등록 성공 주장 안 함** · Draft 유지 · Windows live E2E 미수행

---

## 0. 범위

- 본 문서는 Connector(클라이언트)가 S1 서버 계약과 어떻게 일치하는지만 정의한다.
- 인증·승인·동의 검증·owner/workspace 결정은 전적으로 서버 권한이다. Connector는 인증·승인 기관이 아니다.
- 실제 서버 등록 HTTP 엔드포인트는 아직 존재하지 않는다 (아래 §5 BLOCKED 참조). 그 전까지 모든 live 등록은 fail-closed.

## 1. 등록 경로 (scoped redemption only)

```
사용자 (공식 PADIEM 로그인 표면)
  → challenge_id + one-time pairing_code 수령
    → Connector: build_enrollment_proof_ref() (HMAC-SHA256, §2)
      → EnrollmentRedemptionRequest {challenge_id, device_id, proof_ref}
        → EnrollmentServerPort.redeem_enrollment() (인증된 서버 경로)
          → 성공: 서버 영수증 검증 (§3) → paired_offline 기록
          → 거부: bounded reason 그대로 보고, 바인딩 0건, 로컬 소비 없음
```

- 일반 pairing `redeem()` 경로는 등록에 절대 사용하지 않는다. S1은 enrollment-bound 챌린지를 해당 경로에서
  `enrollment_bound_challenge_requires_scoped_redemption`으로 사전 거부하므로 호출 자체가 성립할 수 없으며,
  본 클라이언트는 해당 호출을 포함하지 않는다 (테스트로 고정).
- 기존 `pairing_client_factory` 인자는 하위 호환용으로만 남고, 등록 흐름에서 호출되면
  `enrollment_scoped_redemption_required`로 즉시 거부한다 (마이그레이션 신호, fail-closed).

## 2. 소유 증명 (proof)

- `build_enrollment_proof_ref(challenge_id, device_id, pairing_code)`:
  key = pairing_code UTF-8, message = `"claw-local-agent-pairing-proof.v1\n{challenge_id}\n{device_id}"` UTF-8,
  HMAC-SHA256 hex, 접두사 `pairing-proof:`. S1 `pairing_proof_ref`와 바이트 동일 (proof-vector 테스트로 고정).
- 원본 pairing_code는 증명 계산에 1회 사용 후 버리며, 저장·로그·재전송하지 않는다.

## 3. 서버 영수증 검증 (`verify_enrollment_receipt`)

- `EnrollmentRedemptionResponse` 이외의 형상은 거부 (서명되지 않은 영수증 불신).
- `ok=False`는 그대로 호출자에 전달 → bounded reason으로 보고, 바인딩 기록 없음.
- `ok=True`는 다음을 모두 만족해야 기록된다: 영수증 device_id == 본 기기 ID (불일치 시
  `enrollment_device_swap_denied`), credential 만료 > now, generation ≥ 1, scope ref 정형.
- 성공은 `paired_offline`으로만 기록된다. `online`/CONNECTED는 이후 서버 projection(`mark_online`) +
  실제 live session이 있어야 하며, 영수증 자체는 lifecycle을 주장하지 않는다.

## 4. 금지 사항 (테스트로 고정)

- LOCAL1의 일반 redeem 차단 로직에 손대지 않음 (해당 파일 미수정).
- 브라우저 쿠키·계정 비밀번호를 Connector로 전달하지 않음 (식별자 스캔 테스트).
- 클라이언트의 `consent_valid=true` 같은 주장을 신뢰하지 않음 (요청 형상에 해당 필드 없음).
- 클라이언트가 owner/workspace를 지정하지 않음 (서버 영수증의 값을 그대로 수용).
- 인증되지 않은 서버 응답으로 등록 성공 처리하지 않음 (형상 검증 + device 대조).
- 새로운 Broker/기기 DB를 만들지 않음 (등록 사실만 기록, 바인딩 발행은 서버).

## 5. 상태 정합성 (기존 모델 재사용, 중복 시스템 없음)

`project_connector_status` + `ConnectionState`를 그대로 사용한다:

| 상태 | 조건 |
| --- | --- |
| `UNREGISTERED` | 미등록 기기 |
| `CONNECTING` | 인증된 등록 또는 연결 진행 중 |
| `CONNECTED` | 서버 확인 ONLINE + 실제 세션 존재 |
| `OFFLINE` | 등록됐으나 연결 없음 |
| `PAUSED` | 사용자 일시중지 |
| `REVOKED` | 등록/자격증명 회수 |

서버 승인 없이 CONNECTED를 표시하지 않는다 (로컬 `connected=True`만으로는 OFFLINE 유지).

## 6. 거부 코드 (S1 bounded 어휘의 클라이언트 측 미러)

`canonical_session_required/inactive`, `enrollment_consent_withdrawn/scope_mismatch/device_mismatch`,
`enrollment_consent_swap_denied`, `enrollment_device_swap_denied`,
`enrollment_binding_owner_mismatch/scope_mismatch`, `enrollment_challenge_expired`,
`enrollment_duplicate_redeem_denied`, `enrollment_proof_invalid`,
`enrollment_consent_liveness_dependency_unmet`, `enrollment_scoped_redemption_required`,
`enrollment_duplicate_device_denied`, `enrollment_binding_revoked_denied`,
`enrollment_credential_expired_denied`, 그 외 → `enrollment_dependency_refused`.
상위 텍스트를 echo하지 않는다. `retryable`은 표시용 힌트이며 자동 재시도를 발생시키지 않는다.

## 7. 서버 연결 미완성 시의 정직한 표시

- `broker_endpoint_configured=false` 또는 서버 포트 미배선 → `UNREGISTERED` + `blocked` 보고, 성공 위장 없음.
- 서버 도달 불가 → `BrokerNotConfiguredError` (blocked JSON, exit 1), CONNECTED 표시 금지.
- 서버 거부 → bounded reason 보고 (exit 2), 바인딩 0건, 동일 챌린지 재시도 가능 (로컬 소비 없음).

## 8. BLOCKED 의존성 (CENTRAL CTO 작업, LOCAL2 범위 밖)

1. **인증된 서버 등록 HTTP 엔드포인트 없음** (`SERVER_ENROLLMENT_ENDPOINT_EXISTS=False`):
   S1은 라이브러리 함수(`issue/redeem_connector_enrollment_challenge`)만 제공하며, pairing HTTP 브릿지는
   일반 경로만 서빙한다. 세션→issue/redeem을 노출하는 제품 라우트(서버 핸들러) 구현이 필요하다.
   불리언 오버라이드 노출 금지.
2. **durable consent authority 미배선** (`DURABLE_CONSENT_AUTHORITY_WIRED=False`,
   S1 `CONSENT_LIVENESS_AUTHORITY_IMPLEMENTED=False`): `CanonicalConsentLivenessPort`의 서버 구현 배선 전까지
   등록은 기본 거부다.
3. **S1 미병합**: `test_s1_contract_drift_guard`는 S1 모듈 import 가능 시에만 실행되며 현재는 skip된다.
   S1 병합 후 해당 테스트가 실제 authority와의 drift를 감시한다.
4. 위 1–3 해결 후: 신규 synthetic PC로 one-shot live E2E (LOCAL2 Connector + 실제 로그인 세션) → CENTRAL 승인.

## 9. 검증 상태 (본 PR HEAD 기준)

- `apps/claw-connect/tests/test_enrollment_contract.py`: 70 passed + 1 skipped (S1 drift guard, BLOCKED)
- `apps/claw-connect/tests/` 전체: 135 passed + 1 skipped
- Node wrapper: 6/6 passed
- Windows live harness (`verify_windows_live.py`): 기존 blocked-기대 항목 유지, live E2E 미수행 (`WINDOWS_LIVE_E2E=NOT_PROVEN`)
- Production: OFF · Ready: NO · Merge: NO
