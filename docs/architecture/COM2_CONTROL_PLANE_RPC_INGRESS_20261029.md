# Control Plane 3종의 대상 측 HTTPS 입구 — 조사와 결정 (2026-10-29)

```text
DOC_ROLE=COM2_CONTROL_PLANE_RPC_INGRESS
STATUS=조사 확정 / (가) identity·google-state 구현 완료(기본 꺼짐, 미배포) / (나) broker 설계만
ISSUE=#5573
RELATED=PR #6142(CPython HttpRpcBinding·v1 proof), COM2_CHAT_SERVICE_BINDINGS_20261029.md
```

## 1. 세 대상은 무엇이고 누가 소유하는가

| Worker | 하는 일 | RPC 메서드(현재) | 소유·경계 |
|---|---|---|---|
| `padiem-control-plane-identity` | canonical 신원 서버: product 사용자 연결, 인증 세션 발급/조회/폐기, connector workspace·context 조회, 테넌트·커넥터 등록 | `Default` 31개 (link/session 7, connector 3, tenant 6, enrollment 12, ticket 1 등) — `identity_authority_worker.py:507-575` | **공유 신원 서버**. 허용 제품은 `_ALLOWED_PRODUCTS = {"b62","b54-padiem-claw","lovetree-4-0"}`(:27), env `CONTROL_PLANE_ALLOWED_PRODUCTS`가 이 집합과 정확히 일치해야 통과(:156-158). 러브트리 로그인(#5963 계열)도 이 서버를 쓴다 |
| `padiem-google-oauth-state` | Google OAuth 상태·커넥터 truth: connect/callback, access lease, workspace connector/calendar state, Drive 바인딩 선택 | `Default` 12개 — `google_oauth_worker.py:392-446` | Control Plane. Chat은 `workspace_connector_state` 하나만 호출(`app/connector_workspace_truth.py:218`) |
| `padiem-local-agent-broker-state` | PC 브로커 DO: 페어링/등록, device 세션, 명령 enqueue/material, poll/ack, device HTTP, device directory, 사무소/텍스트 read | `Default` 30+개 — `local_agent_broker_worker.py:142-260` | Control Plane. 같은 상태 표를 COM2 큐도 쓴다(§2) |

세 대상 모두 지금 `fetch → 404`이고 플래그도 `PUBLIC_FETCH=False` / `PRODUCTION_ROUTE_CONFIGURED=False`다. 즉 HTTPS 계약이 **없다**.

## 2. LOCAL_AGENT_BROKER — 큐와 겹치는가

겹친다. 상태와 경로를 나누면:

- **큐로 흡수되는 부분 (이미 이동 중)**: `pc_pairing_codes`·`pc_device_links`·`mesh_device_presence`는 broker DO와 COM2 큐가 **같은 표**다(`apps/padiem-mesh-queue/schema.py:32-38`). Chat 쪽도 `queue_store_proxy.py`(#6121)가 `QueueBackedPairingStore`/`QueueBackedPresenceStore`로 교체하고 dispatch 이름들을 큐로 넘긴다. executor도 poll·renew·cancel·busy 네 클레임 leg를 큐로 보낸다(PR #6135). 상태 복사는 `copy_state.py`(#6115 계열)가 이미 준비했다.
- **큐로 흡수되지 않은 부분**: device HTTP(`handle_device_http`), 등록/enrollment(`issue_enrollment_challenge`·`redeem_enrollment` 등), device session(`open_session`·`authenticate_device_session`), read API(`read_verified_file_text`·`device_directory`·`read_office_artifact_part`·`terminal_command_result`), 명령 material 저장/조회.

**판정: (나) 단계 이전.** 큐 모양(클레임·페어링·presence)은 COM2 큐가 이미 진실이고, 남은 device/enrollment/session/read 레인은 DO의 원자 상태·자격증명 경계가 핵심이라 HTTPS 입구 하나로 "반쯤" 열면 두 PC 권한 경로가 생긴다. com2 이전 계획의 별도 단계로 옮긴다(§5). 지금은 broker 입구를 만들지 않는다 — PC 레인은 `QUEUE_BACKEND=com2`(기본 off)와 Qoder 큐로만 움직인다.

## 3. 결정

- **IDENTITY_AUTHORITY: (가)**. 공유 신원 서버를 컴2로 옮기는 것은 러브트리까지 포함한 제품 경계 변경이라 범위 밖이고, 세션·링크 RPC는 상태가 없어 HTTPS로 닫기에 적합하다. 단, 허용 메서드를 Chat 병행 호스트가 실제 쓰는 9개로 제한하고(테넌트 관리·connect ticket·enrollment schema/동의는 제외), 기존 RPC·제품 pin은 건드리지 않는다.
- **GOOGLE_OAUTH_STATE: (가)**. Chat이 쓰는 read-only 1개(`workspace_connector_state`)만 연다.
- **LOCAL_AGENT_BROKER: (나)** — §2.

## 4. (가) 구현 — 공통 계약

`packages/padiem-control-plane/internal_rpc_ingress.py` (stdlib only):

| 규칙 | 값 |
|---|---|
| 경로·동사 | `POST /internal/rpc/<method>` (그 외 None → 기존 404 그대로) |
| proof | `v1=hmac_sha256(secret, "v1\n"+METHOD+"\n"+path+"\n"+at+"\n"+body)` — #6142 클라이언트와 동일 |
| 시각 | `x-padiem-service-at` ±300초 |
| 비교 | `hmac.compare_digest`(상수시간) |
| 본문 | 선언 content-length 선검사 + 읽은 뒤 재검사, **512 KiB** 초과 413 |
| 메서드 | worker별 allowlist 외에는 404(목록 비노출) |
| 비밀 없음 | **입구 자체가 없음** — env 바인딩이 없으면 fetch는 지금과 같은 404 |
| 오류 봉투 | `{"ok":false,"error":{"code","message"}}` — 메서드 목록·비밀·업스트림 문구 비노출 |

바인딩 이름: identity `PADIEM_IDENTITY_RPC_INGRESS_SECRET`, google-state `PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET` (평문 str 또는 Secrets Store `.get()` capability 둘 다 수용).

allowlist: identity 9개(link/session 7 + connector workspace·context), google-state 1개.

검증: `packages/padiem-control-plane/tests/test_internal_rpc_ingress.py` 9건 — 클라이언트 v1 수식과 대상 검증기의 일치, 변조·stale·미허용·상한·비POST·비JSON·위임 예외, 비밀 없음→404, 그리고 같은 `Default` 객체의 기존 RPC 메서드가 그대로 동작함(바인딩 경로 불변).

## 5. (나) com2 이전 계획에 넣는 단계 — "Stage 2-C: broker/device 레인"

선행: `QUEUE_BACKEND=com2` 실사용(페어링·presence·dispatch), PC 커넥터 실측 안정화.
내용: broker DO의 device HTTP·enrollment·session·read API를 com2 서비스(가칭 `padiem-broker-state`)로 옮기는 설계 — DO 대신 SQLite+단일 프로세스 잠금, 같은 RPC 이름 유지, 자격증명 검증기는 재사용. 완료 조건: PC 페어링·읽기·명령 왕복이 com2에서 동작하고, Cloudflare broker는 읽기 전용 롤백 경로로 남는다. 이 단계 전까지 Chat CPython의 broker 레인은 fail-closed(현행).

## 6. 배포 절차(하지 않음)

- 배포는 `wrangler deploy` **한 번**에 코드와 비밀을 함께 올린다: 먼저 `wrangler secret put <NAME>`(값은 파일→stdin, 출력 금지) → 같은 SHA로 deploy. 비밀이 없으면 다음 배포에서도 입구는 자동으로 꺼진 채다.
- identity Worker 소스 변경은 `b54-control-plane-identity-production-redeploy` 워크플로의 **PR preflight(읽기 전용)**만 자동 실행된다. 실제 배포는 workflow_dispatch + 확인 문구로만 한다(이 PR은 배포하지 않는다).
- google-state 활성화 워크플로는 그 워크플로 파일 변경에만 반응한다 — 소스 변경으로 자동 배포되지 않는다.
- 공유 신원 서버 주의: 제품 pin(`_ALLOWED_PRODUCTS`·`CONTROL_PLANE_ALLOWED_PRODUCTS`), 기존 RPC 이름·시그니처, 커넥터 동의 경계를 바꾸지 않는다. 이 PR은 fetch 분기와 allowlist 추가뿐이다.

## 7. #6142 클라이언트와의 접속 확인

- 서명 측(CPython `HttpRpcBinding`, #6142)과 검증 측(`internal_rpc_ingress.proof_for`)이 같은 v1 수식을 쓰는 것을 양쪽 테스트로 고정했다. 클라이언트 테스트는 서명 값이 수식과 같은지, 대상 테스트는 그 수식으로 서명한 요청이 200으로 위임되는지 확인한다.
- 실제 왕복은 com2에 origin·secret이 배치되고 대상이 배포된 뒤 `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN/SECRET` 쌍으로 확인한다(그 전에는 fail-closed).
