# PADIEM Connector S2 — 클라이언트 등록 계약 (LOCAL2 → CENTRAL 핸드오프)

**Issues:** #4139 (구현) · **PR:** #4463 (Draft, 미병합) · Windows 통합 PR #4490 (Draft) · 상위 서버 계약: LOCAL1 PR #4438 · 서버 wire 계약: CENTRAL PR #4476
**Client module:** `apps/claw-connect/claw_connect/enrollment.py`
**HTTP adapter / install gate:** `apps/claw-connect/claw_connect/enrollment_http.py`, `apps/claw-connect/claw_connect/credential_install.py`
**Server contract (read-only mirror):** `padiem.connector-enrollment.v1` (`padiem_connector_enrollment.py`, LOCAL1 소유 — 본 PR에서 수정하지 않음)
**Status:** 클라이언트 구현 완료 · **실제 등록 성공 주장 안 함** · Draft 유지 · Windows live E2E 미수행

---

## 0. 범위

- 본 문서는 Connector(클라이언트)가 S1 서버 계약과 어떻게 일치하는지만 정의한다.
- 인증·승인·동의 검증·owner/workspace 결정은 전적으로 서버 권한이다. Connector는 인증·승인 기관이 아니다.
- CENTRAL의 등록 핸들러는 소스에 존재하지만 제품 라우트에 **마운트되지 않았다**
  (`ENROLLMENT_PRODUCT_HTTP_MOUNTED=False`)이고 기기 게이트웨이가 미배선이라, 실제로 도달 가능한 등록
  엔드포인트는 없다 (아래 §5·§8 BLOCKED 참조). 그 전까지 모든 live 등록은 fail-closed다.

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
- **이미 등록된 PC의 계정·스코프 변경은 채택하지 않는다 (fail-closed).** 로컬 바인딩이 존재하고
  `account_ref`가 기록되어 있는데 영수증의 `account_ref`가 다르면
  `enrollment_binding_owner_mismatch`로, `workspace_ref`가 다르면
  `enrollment_binding_scope_mismatch`로 거부하고 **기존 바인딩을 그대로 둔다**(레코드 무변경,
  revoked 아님, project_state는 계속 OFFLINE). 기기 신원은 이전 계정으로 등록된 제품 세션이
  참조하므로, 제자리에서 다른 계정으로 재지정하면 그 세션이 새 계정으로 넘어간다. 의도적 계정
  전환은 `clear_enrollment()`(명시적 로그아웃) 후에만 가능하며, 로그아웃은 바인딩을 먼저 버리므로
  가드가 걸리지 않는다. 두 사유 모두 기존 bounded 어휘의 구성원이고 서버 텍스트를 echo하지 않는다.
  서버 호출 *이후*에 검사하는 이유는 계정이 영수증에서만 알 수 있기 때문이며, 서버는 여전히
  영수증을 발행하는 권위이고 기기는 그것을 **채택하지 않을** 뿐이다.
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
상위 텍스트를 echo하지 않는다. CENTRAL은 redeem 거부에서 항상 `retryable=false`를 보내고, 어댑터는 그 값이 아닌
주장을 계약 위반으로 거부한다. 재시도는 항상 새 챌린지 + 새로운 OWNER 동의이며 동일 챌린지 재사용이 아니다.

## 7. 서버 연결 미완성 시의 정직한 표시

- `broker_endpoint_configured=false` 또는 서버 포트 미배선 → `UNREGISTERED` + `blocked` 보고, 성공 위장 없음.
- 서버 도달 불가 → `BrokerNotConfiguredError` (blocked JSON, exit 1), CONNECTED 표시 금지.
- 서버 거부 → bounded reason 보고 (exit 2), 바인딩 0건. CENTRAL은 redeem 이후 거부에서도 `retryable=false`를
  보내므로 클라이언트는 같은 챌린지를 재시도하지 않는다. 재시도는 새 챌린지 발급 요구로 처리된다.

## 8. BLOCKED 의존성 (CENTRAL CTO 작업, LOCAL2 범위 밖)

1. **등록 라우트가 운영에 마운트되지 않음** (`SERVER_ENROLLMENT_ENDPOINT_EXISTS=False`):
   CENTRAL #4476이 `issue/redeem/consent` 핸들러와 strict wire 계약
   (`PADIEM_CONNECTOR_S2_CENTRAL_HTTP_WIRE_CONTRACT_4139_20261012.md`)을 소스에 확보했지만
   `ENROLLMENT_PRODUCT_HTTP_MOUNTED=False`이고 trusted TLS 기기 게이트웨이가 미배선이다. 마운트·게이트웨이
   배선은 CENTRAL 승인 항목이며, 불리언 오버라이드 노출은 계속 금지된다.
2. **durable consent authority 미배선** (`DURABLE_CONSENT_AUTHORITY_WIRED=False`,
   S1 `CONSENT_LIVENESS_AUTHORITY_IMPLEMENTED=False`): `CanonicalConsentLivenessPort`의 서버 구현 배선 전까지
   등록은 기본 거부다.
3. **S1 미병합**: `test_s1_contract_drift_guard`는 S1 모듈 import 가능 시에만 실행되며 현재는 skip된다.
   S1 병합 후 해당 테스트가 실제 authority와의 drift를 감시한다.
4. 위 1–3 해결 후: 신규 synthetic PC로 one-shot live E2E (LOCAL2 Connector + 실제 로그인 세션) → CENTRAL 승인.

## 9. 검증 상태 (#4490 HEAD에서 실측)

> **LOCAL2 후속 증분 (계정·스코프 격리, 2026-10-13):** 위 §3의 계정/스코프 채택 가드를 추가했다.
> `apps/claw-connect/tests/` 전체 **297 passed, 4 skipped**, `test_enrollment_contract.py`
> **73 passed + 4 skipped** (+6 신규), Node wrapper 5 passed / 0 failed. 신규 테스트 4건은 가드를
> 제거하면 실패함을 음성 대조로 확인했다. `enrollment.py`만 변경했고 `enrollment_http.py`(와이어
> 계약)와 CENTRAL/LOCAL1 파일은 건드리지 않았다.

- `apps/claw-connect/tests/` 전체: **291 passed, 4 skipped** (로컬 Windows Python 3.11, 실제 DPAPI 포함; CI는 3.12에서 재실행)
  - skip 3건: `CENTRAL-CONTRACT-CONFLICT` — central `dbbd1633`가 `claw_connect.resident_path`와
    `runtime.ConnectApp(enrollment=...)` 배선을 제거해 재현 불가 (Resident 경로는 #4139 범위 밖, CENTRAL 결정 대기)
  - skip 1건: S1 authority 미병합 drift guard (`BLOCKED_DEPENDENCY`)
- `test_enrollment_contract.py`: 67 passed + 4 skipped
- `test_enrollment_http_transport.py` + `test_credential_install_confirmation.py` + `test_enrollment_install_gate.py`: 156 passed
  - credential ceiling/floor와 pairing transcript의 authority cross-check는 canonical authority **소스에서
    literal을 읽어** 고정한다(import 하지 않는다). Connector CI 게이트는 pytest만 설치하는데
    `padiem_control_plane`은 `padiem_ai_core`까지 도달해서, import 방식은 개발 PC(무관한 editable install이
    존재)에서만 통과하고 Windows CI에서 실패했다 — 그 차이가 실제 CI 신호로 관측돼 수정된 것이다.
    literal 읽기는 `sys.path`/`sys.modules`를 건드리지 않아 위 S1 drift guard의 in-process skip 결정을
    조용히 바꾸지 않는다
- `test_credential_install_windows_dpapi_store.py`: **11 passed** — 실제 `kagent.ProtectedFileDeviceCredentialStore`
  + 실제 current-user DPAPI로 save·readback 확인, 디스크에 plaintext 없음, binding 컨텍스트 바인딩,
  revoked/expired binding 거부, save 이후 기록이 손상되면 readback에서 거부, delete 후 비밀 제거,
  single-use까지 검증
- Node wrapper (`npm test`): **5 passed / 0 failed** (이전 문서의 6/6은 오기재였고 실측은 5건)
- GitHub Windows 게이트(`claw-connect-contract-tests.yml`, PR #4490 head에서 실행): §11에 exact SHA로 보고
- Windows live harness (`verify_windows_live.py`): 기존 blocked-기대 항목 유지, live E2E 미수행 (`WINDOWS_LIVE_E2E=NOT_PROVEN`)
- Production: OFF · Ready: NO · Merge: NO

## 10. HTTP 어댑터와 로컬 설치 게이트 (#4490 추가분)

`enrollment_http.py` — CENTRAL redeem wire의 유일한 클라이언트 측 경계:

- 요청은 3키(`challenge_id`,`device_id`,`proof_ref`)만 전송. 쿠키·토큰·session·owner·consent는 절대 실지 않는다.
- 성공 응답은 top-level이 정확히 `{ok, enrollment}`이고 receipt가 게시된 13키와 **정확히** 일치해야 한다.
  추가키(`credential_b64`, 토큰, owner 주장, fingerprint 등)는 즉시 거부 — 시크릿 투기와 forge를 이 경계에서 자른다.
- `consent_id`는 CENTRAL이 발행한다(CENTRAL #4476 이후 전송됨). 어댑터는 필수 필드로 검증하며 **절대 합성하지 않는다**.
- `credential_installed_by_canonical_handoff=true`, `lifecycle=paired_offline`, 모든 권한 booleans=false,
  만료 > now, device_id 일치, ref 형상(`_SAFE_VALUE` 미러)까지 통과해야 `EnrollmentRedemptionResponse` 성공이 된다.
- 거부 응답은 `{ok,error:{code},reason,retryable:false}` 폐형상만 허용. `reason`은 S2 어휘 소속이어야 하고,
  `error.code`는 shape 검증 후 **폐기**(UI·로그·보관 불가). `retryable=true` 주장은 계약 위반으로 거부.
- status와 본문 불일치는 양방향 거부(200+`ok:false`, non-2xx+`ok:true` 모두 raise).

`credential_install.py` — 로컬 설치 확인은 서버 플래그가 아니라 canonical 보호 저장소로 만든다:

- `save`가 돌려준 projection이 **넘겨받은 binding과 동일한** `binding_ref`·`device_id`·`credential_generation`을
  가져야 하고(비정상/오래된 binding의 projection은 절대 `installed=True`가 되지 않음), 같은 binding 컨텍스트로
  `load` readback한 바이트가 원본과 일치해야 한다. readback 능력이 없는 저장소는 사용 불가로 처리한다.
- proof kind는 CENTRAL 설치 ack가 요구하는 `protected_store_save_readback` 하나만 인정한다.
- save와 readback이 모두 확인된 뒤에만 CENTRAL의 versioned transcript
  (`padiem.connector-device-install-ack.v1`, 개행 구분, trailing newline 없음)에 새 자격증명을 키로
  HMAC-SHA256 proof를 계산해 confirmation에 담는다. 이 proof는 자격증명 *소유*만 증명하며 DPAPI 설치나
  Windows 기기 신원을 증명하지 않는다. 전송 채널이 미선정이라 어떤 sender도 배선하지 않았고,
  CENTRAL이 검증할 수 없는 길이(16–4096 bytes 창 밖)의 자격증명은 저장 전에 거부한다.
  이 창은 #4139 Decision A의 규범값이다 — ceiling은
  `padiem_control_plane.local_agent_broker_pairing.MAX_PAIRING_CREDENTIAL_BYTES`(4096, 기본 발급은 32 bytes)이고,
  generic DPAPI 저장 용량(16384)을 초과할 근거가 아니다. 테스트가 두 canonical authority에서 실제 값을 읽어
  미러 상수를 고정한다.
- redeemed 챌린지는 로컬에서도 single-use: 시도(성공·실패 무관)마다 소비된다.
- 설치 실패 복구는 `plan_install_failure_recovery(revocation_confirmed=…)`가 두 가지로만 매핑한다 —
  canonical 회수 확인 → `new_challenge_required`, 미확인/모호 → `security_hold_reconciliation_required`.
  두 경로 모두 `report_enrolled=false`, `retry_same_challenge=false`, `retransmit_credential=false`이며
  OWNER 재동의 없이는 재발급되지 않는다. Connector는 스스로 Broker binding을 회수하지 않고 회수 결과를 주장하지 않는다.
- CENTRAL→PC 자격증명 전달 채널은 여전히 미정의 (`CREDENTIAL_HANDOFF_WIRED=False`), live OS 배선 없음.
