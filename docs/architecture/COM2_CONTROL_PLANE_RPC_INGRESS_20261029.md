# Control Plane 3종의 대상 측 HTTPS 입구 — 조사와 결정 (2026-10-29)

```text
DOC_ROLE=COM2_CONTROL_PLANE_RPC_INGRESS
STATUS=10월 29일 조사 기록 / Google 현재 계약은 #7091·#7094 및 아래 11월 8일 정합화 참조
ISSUE=#5573
RELATED=PR #6142(CPython HttpRpcBinding·v1 proof), COM2_CHAT_SERVICE_BINDINGS_20261029.md
```

## 2026-11-08 Google 정합화

#7089의 기능은 #7091(배선), #7094(Calendar ingress·설정)에 흡수됐다.
현재 Chat은 기본 `HttpRpcBinding`의 v2 + 서명된 요청 ID를 사용한다.
v1은 대상 `PADIEM_RPC_SERVICE_ID_POLICY=optional`일 때만 호환되고,
`required`이면 `403 rpc_service_id_required`다. 기존 테스트나 정책을
낮추지 않고 main의 v2 조립을 유지한다. 실제 배포 여부는 운영 조회로 별도 확인한다.

## 1. 세 대상은 무엇이고 누가 소유하는가

| Worker | 하는 일 | RPC 메서드(현재) | 소유·경계 |
|---|---|---|---|
| `padiem-control-plane-identity` | canonical 신원 서버: product 사용자 연결, 인증 세션 발급/조회/폐기, connector workspace·context 조회, 테넌트·커넥터 등록 | `Default` 31개 (link/session 7, connector 3, tenant 6, enrollment 12, ticket 1 등) — `identity_authority_worker.py:507-575` | **공유 신원 서버**. 허용 제품은 `_ALLOWED_PRODUCTS = {"b62","b54-padiem-claw","lovetree-4-0"}`(:27), env `CONTROL_PLANE_ALLOWED_PRODUCTS`가 이 집합과 정확히 일치해야 통과(:156-158). 러브트리 로그인(#5963 계열)도 이 서버를 쓴다 |
| `padiem-google-oauth-state` | Google OAuth 상태·커넥터 truth: connect/callback, access lease, workspace connector/calendar state, Drive 바인딩 선택 | `Default` 12개 — `google_oauth_worker.py:392-446` | Control Plane. Chat은 `workspace_connector_state`와 `workspace_calendar_connector_state` 두 read-only RPC를 호출(`app/connector_workspace_truth.py`) |
| `padiem-local-agent-broker-state` | PC 브로커 DO: 페어링/등록, device 세션, 명령 enqueue/material, poll/ack, device HTTP, device directory, 사무소/텍스트 read | `Default` 30+개 — `local_agent_broker_worker.py:142-260` | Control Plane. 같은 상태 표를 COM2 큐도 쓴다(§2) |

10월 29일 최초 조사에서는 세 대상 모두 `fetch → 404`였다. 현재 Google은
#7094의 signed HTTPS ingress와 workers.dev 설정을 사용하며, ingress secret이
없으면 404로 닫힌다. 이 소스 설정을 실제 배포 완료로 해석하지 않는다.

## 2. LOCAL_AGENT_BROKER — 큐와 겹치는가

겹친다. 상태와 경로를 나누면:

- **큐로 흡수되는 부분 (이미 이동 중)**: `pc_pairing_codes`·`pc_device_links`·`mesh_device_presence`는 broker DO와 COM2 큐가 **같은 표**다(`apps/padiem-mesh-queue/schema.py:32-38`). Chat 쪽도 `queue_store_proxy.py`(#6121)가 `QueueBackedPairingStore`/`QueueBackedPresenceStore`로 교체하고 dispatch 이름들을 큐로 넘긴다. executor도 poll·renew·cancel·busy 네 클레임 leg를 큐로 보낸다(PR #6135). 상태 복사는 `copy_state.py`(#6115 계열)가 이미 준비했다.
- **큐로 흡수되지 않은 부분**: device HTTP(`handle_device_http`), 등록/enrollment(`issue_enrollment_challenge`·`redeem_enrollment` 등), device session(`open_session`·`authenticate_device_session`), read API(`read_verified_file_text`·`device_directory`·`read_office_artifact_part`·`terminal_command_result`), 명령 material 저장/조회.

**판정: (나) 단계 이전.** 큐 모양(클레임·페어링·presence)은 COM2 큐가 이미 진실이고, 남은 device/enrollment/session/read 레인은 DO의 원자 상태·자격증명 경계가 핵심이라 HTTPS 입구 하나로 "반쯤" 열면 두 PC 권한 경로가 생긴다. com2 이전 계획의 별도 단계로 옮긴다(§5). 지금은 broker 입구를 만들지 않는다 — PC 레인은 `QUEUE_BACKEND=com2`(기본 off)와 Qoder 큐로만 움직인다.

## 3. 결정

- **IDENTITY_AUTHORITY: (가)**. 공유 신원 서버를 컴2로 옮기는 것은 러브트리까지 포함한 제품 경계 변경이라 범위 밖이고, 세션·링크 RPC는 상태가 없어 HTTPS로 닫기에 적합하다. 단, 허용 메서드를 Chat 병행 호스트가 실제 쓰는 9개로 제한하고(테넌트 관리·connect ticket·enrollment schema/동의는 제외), 기존 RPC·제품 pin은 건드리지 않는다.
- **GOOGLE_OAUTH_STATE: (가)**. Chat이 쓰는 read-only 2개(`workspace_connector_state`, `workspace_calendar_connector_state`)만 연다. Calendar는 별도 상태 조회이며 #2830의 기본 Gmail+Drive projection을 넓히지 않는다. connect/callback·lease·binding 선택·관리 메서드는 이 HTTPS allowlist에 없다.
- **LOCAL_AGENT_BROKER: (나)** — §2.

## 4. (가) 구현 — 공통 계약

`packages/padiem-control-plane/internal_rpc_ingress.py` (stdlib only):

| 규칙 | 값 |
|---|---|
| 경로·동사 | `POST /internal/rpc/<method>` (그 외 None → 기존 404 그대로) |
| proof | 현재 RPC 기본값: `v2=hmac_sha256(secret, "v2\n"+METHOD+"\n"+path+"\n"+at+"\n"+service_id+"\n"+body)`. `x-padiem-service-id`를 서명에 포함 |
| 시각 | `x-padiem-service-at` ±300초 |
| 비교 | `hmac.compare_digest`(상수시간) |
| 요청 ID | 매 시도 새 ID, 대상 DO replay guard가 중복 요청을 `409 rpc_replay_detected`로 거부 |
| 본문 | 선언 content-length 선검사 + 읽은 뒤 재검사, **512 KiB** 초과 413 |
| 메서드 | worker별 allowlist 외에는 404(목록 비노출) |
| 비밀 없음 | **입구 자체가 없음** — env 바인딩이 없으면 fetch는 지금과 같은 404 |
| 오류 봉투 | `{"ok":false,"error":{"code","message"}}` — 메서드 목록·비밀·업스트림 문구 비노출 |

바인딩 이름: identity `PADIEM_IDENTITY_RPC_INGRESS_SECRET`, google-state `PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET` (평문 str 또는 Secrets Store `.get()` capability 둘 다 수용).

allowlist: identity 9개(link/session 7 + connector workspace·context), google-state 2개.

COM2 이름은 `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN` /
`PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET`이다. origin은 배포된 state Worker의
bare HTTPS origin, secret은 대상 `PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET`와
같은 값이다. #7089의 `...GOOGLE_OAUTH_RPC_ORIGIN/SECRET`는 사용하지 않는다.
값을 출력하지 않고 존재 여부와 SHA-256 앞 8자리로만 비교한다.

기존 검증: `packages/padiem-control-plane/tests/test_internal_rpc_ingress.py` — 클라이언트 v1 수식과 대상 검증기의 일치, 변조·stale·미허용·상한·비POST·비JSON·위임 예외, 비밀 없음→404, 그리고 같은 `Default` 객체의 기존 RPC 메서드가 그대로 동작함(바인딩 경로 불변).

## 5. (나) com2 이전 계획에 넣는 단계 — "Stage 2-C: broker/device 레인"

상세 설계(원자성·자격증명 경계·전환 순서·원복·차동 테스트):
`docs/architecture/COM2_BROKER_STAGE2C_DESIGN_20261029.md`.

선행: `QUEUE_BACKEND=com2` 실사용(페어링·presence·dispatch), PC 커넥터 실측 안정화.
내용: broker DO의 device HTTP·enrollment·session·read API를 com2 서비스(가칭 `padiem-broker-state`)로 옮기는 설계 — DO 대신 SQLite+단일 프로세스 잠금, 같은 RPC 이름 유지, 자격증명 검증기는 재사용. 완료 조건: PC 페어링·읽기·명령 왕복이 com2에서 동작하고, Cloudflare broker는 읽기 전용 롤백 경로로 남는다. 이 단계 전까지 Chat CPython의 broker 레인은 fail-closed(현행).

## 6. 배포 절차(하지 않음)

- 실제 배포·secret 변경은 CTO가 정식 배포 절차로 수행한다. Google state는 `b54-google-oauth-state-production-redeploy`의 workflow_dispatch 경로를 사용한다. 기존 secret 존재 여부를 먼저 읽고, 필요한 추가만 승인된 비공개 출처에서 입력한다. 비밀이 없으면 ingress는 404로 닫힌다.
- identity Worker 소스 변경은 `b54-control-plane-identity-production-redeploy` 워크플로의 **PR preflight(읽기 전용)**만 자동 실행된다. 실제 배포는 workflow_dispatch + 확인 문구로만 한다(이 PR은 배포하지 않는다).
- google-state 활성화 워크플로는 그 워크플로 파일 변경에만 반응한다 — 소스 변경으로 자동 배포되지 않는다.
- 공유 신원 서버 주의: 제품 pin(`_ALLOWED_PRODUCTS`·`CONTROL_PLANE_ALLOWED_PRODUCTS`), 기존 RPC 이름·시그니처, 커넥터 동의 경계를 바꾸지 않는다. 이번 정합화 PR은 문서와 회귀 테스트만 바꾸며 배포하지 않는다.

## 7. 서명 접속 검증

- #6142의 초기 v1 계약 뒤에 요청 ID가 서명에 결속되는 v2가 추가됐다. 현재 기본 `HttpRpcBinding`과 Google `Default.fetch`의 실제 검증/DO를 연결하는 `test_com2_google_oauth_rpc_integration.py`로 두 read-only 상태 조회, required 정책, replay 거부와 닫힌 allowlist를 검증한다.
- 실제 Google 왕복은 COM2의 `PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN/SECRET` 쌍과 대상 배포를 확인한 뒤 아래 절차로 검증한다(그 전에는 fail-closed). Identity RPC는 별도 env 쌍이다.


## 8. Google 커넥터 배포 후 확인

CTO가 기존 env 이름·대상 secret 출처·배포 버전을 먼저 확인한다. 필요한
변경만 기존 배포 절차로 적용하며, 이 문서/테스트 PR은 env·서비스·배포를
변경하지 않는다. 정상 구성된 이름이나 secret을 중복 추가하거나 회전하지 않는다.

1. 대표 로그인 세션에서 `GET /api/connectors/status`를 1회 확인한다.
   `workspace_state_authority=true`, Google 세 행의 `workspace_state`가
   `connected` / `not_connected` / `ambiguous` 중 실제 상태이며
   `canonical_workspace_truth_unavailable`가 없어야 한다.
   `verified`라는 상태 문자열은 없다. `not_connected`도 검증된 미연결
   상태이므로 전송 실패와 구분한다.
2. 같은 로그인 세션·정확한 Origin·`Content-Type: application/json`으로
   `POST /api/connectors/google/calendar/activate-read`에 `{}`를 보낸다.
   완료는 HTTP 200, `calendar_read_grant=active`,
   `calendar_write_authorized=false`다.
3. `calendar_activation_not_connected`면 대표 계정으로 Google Calendar
   연결을 완료한 뒤 같은 활성화를 다시 확인한다. 실제 계정 연결은 이
   코드 회귀 테스트의 범위가 아니다. 401/403은 앞단 인증/Origin 거부일 수
   있어, 단순히 503이 아니라는 이유로 배선 성공으로 판정하지 않는다.
4. `calendar_read_activation_unavailable` 또는 다른 5xx이면 Chat P01
   조립·대상 호출자 인증·대상 배포 상태를 오류 코드로 구분한다. 원시 응답,
   쿠키·proof·토큰·env 값은 로그나 PR에 남기지 않는다.
