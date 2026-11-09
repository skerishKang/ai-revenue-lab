# 컴2 P01 호스트 — Control Plane identity·Google OAuth state·connector grants 바인딩 설계

이슈: #7229 (#7227 후속). 대상 코드: `apps/padiem-ai-engine/app/local_runtime.py`.

## 1. 지금 막힌 곳

Cloudflare에서는 P01 Engine이 세 개의 신뢰 바인딩을 받는다.

| Worker 바인딩 | `wrangler.toml` | 실제 권위 |
| --- | --- | --- |
| `CONTROL_PLANE_IDENTITY` | `[[services]] service = "padiem-control-plane-identity"` (`apps/padiem-ai-engine/wrangler.toml:43`) | `packages/padiem-control-plane/identity_authority_worker.py` |
| `CONTROL_PLANE_GOOGLE_OAUTH` | `[[services]] service = "padiem-google-oauth-state"` (`:54`) | `packages/padiem-control-plane/google_oauth_worker.py` |
| `ENGINE_CONNECTOR_GRANTS` | `[[d1_databases]] database_name = "padiem-engine"` (`:88`) | Engine 자기 D1 (`padiem_engine_connector_grants`, 마이그레이션 `0003`) |

캘린더 활성화·상태 서비스는 이 셋을 모두 요구한다(`worker_identity.py:816`–`836`). 하나라도 없으면 서비스가 `None`이 되고 Engine은 `503 calendar_activation_unavailable`을 낸다(`worker_identity.py:1563`–`1568`).

컴2 호스트는 `_local_bindings`(`local_runtime.py:697`–`740`)에서 다음만 만든다.

```
B14_SERVICE, PADIEM_CHAT_SERVICE, ENGINE_IDEMPOTENCY,
admission_binding_for(values)   -> CONTROL_PLANE_ENGINE_ADMISSION
identity_binding_for(values)    -> CONTROL_PLANE_IDENTITY
```

즉 identity는 이미 있고, **`CONTROL_PLANE_GOOGLE_OAUTH`와 `ENGINE_CONNECTOR_GRANTS`가 없어** 서비스 합성이 실패한다. 게다가 호스트 identity 바인딩(`local_identity_binding.py:20`)은 `resolve_auth_session`만 노출하고, 캘린더 경로가 호출하는 `resolve_connector_workspace`(`calendar_read_activation.py:91`)가 없다. 그래서 두 바인딩만 채워도 다음 호출에서 `calendar_activation_identity_unavailable`로 막힌다.

## 2. 방식 결정 — 새 부품을 만들지 않고 이미 있는 두 부품을 재사용한다

### 2.1 identity: 기존 v2 RPC 전송 재사용 (코드 추가 최소)

- `local_identity_binding.HttpsIdentityBinding`은 `local_admission_binding.HttpsAdmissionBinding`의 HTTPS/v2 proof 전송을 그대로 쓴다.
- 컴2 identity ingress(`com2_identity_rpc_ingress.py:35` `COM2_IDENTITY_RPC_METHODS`)는 **이미 `resolve_connector_workspace`를 허용**한다. 새 인증 규약·키·권한이 필요 없다.
- 결정: 같은 전송에 `resolve_connector_workspace` 메서드 하나만 추가한다. 새 env 이름은 없다(기존 `PADIEM_ENGINE_LOCAL_IDENTITY_ORIGIN/_SECRET`).

### 2.2 Google OAuth state: Chat이 이미 쓰는 것과 같은 HTTPS RPC 형태

- Chat(`apps/padiem-chat/app/local_cpython.py:303`–`317`)은 `HttpRpcBinding`(=`apps/padiem-chat/app/local_service_bridge.py`)으로 state Worker의 `POST /internal/rpc/<method>`를 v2 proof로 호출한다. env 이름은 `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN/_SECRET`.
- Engine 쪽 P01은 이미 **같은 v2 proof 전송**(`HttpsAdmissionBinding._post_signed`)과 서비스 id 재시도 규약을 갖고 있다. 새 클라이언트 모듈을 하나 더 만들지 않고, 그 전송 위에 얇은 어댑터만 얹는다(`local_google_oauth_binding.py`, 기존 `local_identity_binding.py`와 같은 모양).
- 어댑터가 노출하는 메서드는 Engine이 실제로 호출하는 것 하나뿐이다: `select_calendar_binding`(`calendar_read_activation.py:131`, `calendar_read_state.py:107`). 그 외 state Worker 메서드는 열지 않는다.
- **선행 조건(Control Plane 변경, 별도 배포)**: state Worker의 HTTPS ingress 허용 목록(`google_oauth_worker.py:400`–`406`)에는 지금 `workspace_connector_state`, `workspace_calendar_connector_state` 두 개만 있다. `select_calendar_binding`은 binding 전용이라 원격 호출이 404/`rpc_method_not_allowed`로 거부된다. 이 메서드를 ingress 목록에 추가하는 변경과 그 Worker 배포가 먼저 필요하다. 비밀은 이미 존재하는 `PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET` 그대로다.
- 비밀 재사용: 컴2에는 Chat이 같은 state Worker에 붙는 데 쓰는 값이 이미 있고(= `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET`), P01은 **그 값과 동일한 값**을 자기 이름으로 갖는다. 새 비밀 자료를 만들지 않는다.

### 2.3 connector grants: 호스트의 기존 엔진 DB 객체를 그대로 두 번째 이름으로

- Cloudflare에서 `ENGINE_CONNECTOR_GRANTS`는 `ENGINE_IDEMPOTENCY`와 **같은 D1 데이터베이스**다(`wrangler.toml:78` vs `:88`, 둘 다 `padiem-engine` / `6b77ad02-…`). 스키마는 `migrations/0003_engine_connector_grants.sql`.
- 컴2 호스트는 이미 같은 스키마의 로컬 엔진 DB를 `ENGINE_IDEMPOTENCY`로 바인딩하고, 부팅 시 `apply_engine_migrations`로 0003을 포함한 전체 마이그레이션을 적용한다(`local_sqlite_d1.py:111`).
- 결정: `ENGINE_CONNECTOR_GRANTS`에 **같은 객체**를 등록한다. 새 저장소·새 마이그레이션·새 자격 증명이 없고, Cloudflare와 같은 "한 DB 두 이름" 구조를 호스트에서 그대로 재현한다. grant 행은 이 호스트의 활성화 경로가 직접 쓰고 읽으므로(`connector_grants_d1.py:364` `activate_calendar_read_grant`) 자기 일관적이다.

### 2.4 기각한 대안

| 대안 | 기각 이유 |
| --- | --- |
| state Worker용 새 비밀·새 서명 규약 도입 | 이미 ingress secret과 v2 proof 계약이 있고 Chat이 같은 계약을 쓴다. 두 번째 계약은 감사 면적만 늘린다. |
| D1 grants를 HTTPS로 프록시하는 새 서비스 | 존재하지 않는 부품을 새로 만드는 일이고, Cloudflare 쪽에서도 grants는 "Engine 자기 DB"다. |
| grants를 로컬 빈 SQLite로 두고 `calendar_not_connected`로 fail-closed | 503이 409로 바뀔 뿐 기능은 그대로 막힌다. 원인 은폐. |
| env 없을 때 로컬 대체물로 성공 흉내 | 권위 없는 통과. 금지. |

## 3. env 이름 목록 (값 없음)

| 위치 | 이름 | 의미 | 신규 |
| --- | --- | --- | --- |
| P01 `p01.env` | `PADIEM_ENGINE_LOCAL_IDENTITY_ORIGIN` | identity Worker/ingress bare HTTPS origin | 기존 |
| P01 `p01.env` | `PADIEM_ENGINE_LOCAL_IDENTITY_SECRET` | 위 ingress 서명 비밀 | 기존 |
| P01 `p01.env` | `PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_ORIGIN` | state Worker(`padiem-google-oauth-state`) bare HTTPS origin | **신규** |
| P01 `p01.env` | `PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_SECRET` | state Worker ingress 서명 비밀 | **신규** |
| P01 `p01.env` | `PADIEM_ENGINE_LOCAL_DB` | 호스트 엔진 SQLite 경로(grants·idempotency 공용) | 기존 |

Chat 쪽 이름은 바뀌지 않는다: `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN`, `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET`, `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN/_SECRET`, `PADIEM_CHAT_LOCAL_P01_ENGINE_*`.

## 4. 비밀 쌍과 반대편 위치

| 호스트 env (P01) | 반대편(Cloudflare) 이름 | 반대편 위치 | 비고 |
| --- | --- | --- | --- |
| `PADIEM_ENGINE_LOCAL_IDENTITY_SECRET` | `PADIEM_IDENTITY_RPC_INGRESS_SECRET` | identity-authority Worker (`identity_authority_worker.py`), 컴2 identity ingress 프록시 | 기존 값. Chat의 `PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET`과 같은 비밀 |
| `PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_SECRET` | `PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET` | state Worker `Default.RPC_INGRESS_SECRET_BINDING` (`google_oauth_worker.py:404`) | 기존 값. Chat의 `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET`과 같은 비밀 |
| (해당 없음) | — | — | grants는 로컬 엔진 DB. 비밀 없음 |

origin도 쌍으로 본다: `PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_ORIGIN`은 Chat의 `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN`과 같은 값을 쓴다. 같은 state Worker에 두 호스트가 각자 이름으로 붙는 구조이며, 한쪽만 바뀌면 그쪽만 503으로 남는다.

## 5. fail-closed 계약 (머지해도 동작이 바뀌지 않는 이유)

| 설정 상태 | 호스트 바인딩 | 결과 |
| --- | --- | --- |
| 두 신규 env 모두 없음(현재 운영) | `CONTROL_PLANE_GOOGLE_OAUTH` 없음 | 서비스 `None` → 지금과 동일한 `503 calendar_activation_unavailable` |
| origin만 있고 secret 없음 / secret 32자 미만 / https 아님 / 경로·쿼리 포함 | 바인딩 없음 | 위와 동일. 부팅 오류로 승격하지 않는다(기존 `identity_binding_for`·`admission_binding_for`와 같은 규약) |
| 둘 다 있음 + Worker ingress가 `select_calendar_binding` 허용 | 바인딩 있음 | 활성화 경로가 state Worker까지 도달. ingress가 거부하면 기존 어댑터가 `calendar_activation_*_unavailable`로 fail-closed |
| grants DB 경로 없음 | `ENGINE_CONNECTOR_GRANTS` 없음 | 서비스 `None` → 503 |

비밀·origin·응답 원문은 로그·예외 메시지·argv로 나가지 않는다(기존 전송의 규약을 그대로 상속).

## 6. 시험

`apps/padiem-ai-engine/tests/test_com2_control_plane_bindings.py`

1. **계약 고정**: `worker_identity.py`의 두 합성 함수가 요구하는 바인딩 이름 집합과, `local_runtime._local_bindings`가 설정 완료 시 제공하는 이름 집합을 비교해 어긋나면 실패. 한쪽만 고쳐도 red.
2. fail-closed: 신규 env 없음/부분/형식 오류에서 세 이름이 모두 사라지고 합성이 `None` → 503 경로 유지.
3. identity: `resolve_connector_workspace`가 `/internal/rpc/resolve_connector_workspace`로 v2 proof와 함께 나가고 실제 ingress가 받는다.
4. google oauth: `select_calendar_binding`이 `/internal/rpc/select_calendar_binding`으로 나가고, ingress 거부 시 `RuntimeError`에 비밀·URL·본문이 없다.
5. grants: 같은 DB 객체가 `ENGINE_IDEMPOTENCY`와 `ENGINE_CONNECTOR_GRANTS` 두 이름에 등록되고, `CloudflareD1ConnectorGrantStore`가 실제 테이블에서 `load_calendar_grants`를 읽는다.

기존 시험(activation/state/admission/identity/꾸러미)도 함께 녹색이어야 한다.

## 7. 배포에 필요한 운영 작업 (이번 작업에서는 실행하지 않음)

1. **선행**: state Worker ingress 허용 목록에 `select_calendar_binding` 추가 PR → 머지 → state Worker 배포. 이게 없으면 P01은 계속 503이다.
2. 컴2 `/opt/padiem/p01/env/p01.env`에 두 이름 추가(값은 기존 비밀 저장소에서만). 변경 전 파일을 root 0600으로 복제해 롤백 지점 확보. 값은 출력하지 않는다.
3. `PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_SECRET`이 state Worker의 ingress secret과 같은지, origin이 Chat의 origin과 같은지 **비노출 방식**(해시 비교·존재 확인)으로 확인.
4. P01 재기동 후: `/internal/v1/health` 200, 캘린더 활성화 1회, `calendar_read_grant_state`가 `unavailable`이 아닌 값으로 바뀌는지 확인.
5. 롤백: env 복제본 복원 + 이전 release checkout 복귀(기존 `deploy_from_main.sh` 이전 디렉터리 규약).
6. Chat 배포는 이 작업에 포함하지 않는다(코드 변경이 Chat에 없음).

## 8. 남는 위험

- state Worker ingress가 열린 뒤에는 Engine 호스트가 `select_calendar_binding`을 호출할 수 있다. 호출자는 v2 proof + 서비스 id 재사용 방지로 제한되고, 응답은 `binding_ref`/`actor_ref`만 담는 기존 계약을 유지한다. 다만 노출면이 하나 늘어나는 변경이므로 Control Plane 쪽 리뷰를 별도로 받는다.
- grants를 호스트 로컬 DB로 두면 Cloudflare D1의 grants와 컴2의 grants는 서로 다른 사본이다. 캘린더 READ grant는 활성화한 호스트가 스스로 쓰고 읽으므로 기능상 일관되지만, 두 사본을 같은 것으로 가정하는 상위 기능(예: Cloudflare에서 활성화한 grant를 컴2가 읽는 것)은 지원하지 않는다. 필요해지면 그때 별도 이슈로 다룬다.
