# 컴2 이전 2단계 A — Chat의 서비스 바인딩 8종과 CPython 대체 (2026-10-29)

```text
DOC_ROLE=COM2_CHAT_SERVICE_BINDING_MAP
STATUS=표·원인 확정 / CPython 대체 구현: B14·PDF·identity RPC 클라이언트 (로컬 플래그 뒤)
ISSUE=#5573
RELATED=docs/architecture/COM2_CHAT_CPYTHON_STAGE2_20261029.md (2단계 본편), PR #6130
```

## 1. 요약

Worker는 같은 계정의 Service binding으로 형제 Worker를 부른다. 일반 CPython
프로세스에는 그 통로가 없으므로, **이 저장소가 통제할 수 있는 것은 Chat 쪽
클라이언트**다. 대체는 두 모양 중 하나다.

- **fetch형**(HTTP 계약이 이미 있음): 같은 경로·같은 JSON·같은 응답 상한을
  HTTPS로 호출 + 서비스 간 비밀(HMAC proof). 대상 Worker를 Cloudflare Tunnel
  호스트로 노출하고, **대상 쪽이 proof를 검증**해야 완성된다.
- **RPC형**(Workers RPC 메서드만 있음): `POST /internal/rpc/<method>` +
  proof 라는 **새 HTTP 표면을 대상이 열어야** 한다. 현재 대상들은
  `fetch → 404`, `PRIVATE_SERVICE_BINDING_RPC=True`, 공개 라우트 없음이라
  Chat 쪽 클라이언트만으로는 완성되지 않는다. 이 경우 레인은 지금처럼
  fail-closed로 남기고, 표에 필요한 결정을 남긴다.

proof 형식(양쪽 공유 계약, `app/local_service_bridge.py`):

```text
x-padiem-service-at:    <unix 초>
x-padiem-service-proof: v1=hex(hmac_sha256(secret, "v1\n"+method+"\n"+path+"\n"+at+"\n"+body))
```

## 2. 8종 대체표

| # | 바인딩 | 무엇인가 | Worker에서 | CPython 현황 | 필요한 것 |
|---|---|---|---|---|---|
| 1 | `B14_SERVICE` (ai-revenue-korean-ai-platform) | 모델 실행·스트리밍 (플랫폼 자격증명) | binding fetch + `PADIEM_B14_SERVICE_PROOF_SECRET` 헤더 (`app/b14_upstream_composition.py:61-97`) | **구현 완료** — `B14_UPSTREAM_MODE=https` + `B14_UPSTREAM_URL` + proof 시크릿으로 `DispatchAwareB14Client` 구성 (`app/local_cpython.py`) | Owner 승인 B14 엔드포인트·시크릿 배포 (모델 결정은 Owner 소유) |
| 2 | `IDENTITY_AUTHORITY_SERVICE` (padiem-control-plane-identity) | canonical identity RPC (product link·auth session·connector workspace) | RPC 메서드 호출 (`app/control_plane_identity_worker.py:182+`) | **대상 입구 구현(미배포·기본 꺼짐)** — `/internal/rpc/<method>` + v1 proof, allowlist 9개. 비밀 미설정 시 기존 404 그대로 | 배포(코드+비밀 1회 deploy) 후 com2 env 쌍 배치 — `COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md` |
| 3 | `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE` (padiem-local-agent-broker-state) | PC 커넥터 페어링/브로커 상태 (RPC) | RPC 메서드 호출 | **(나) 단계 이전** — 클레임·페어링·presence는 COM2 큐가 진실(`queue_store_proxy.py`, #6121). device/enrollment/session/read는 Stage 2-C로 이전 | Stage 2-C 설계(`COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md` §5). 그 전까지 PC 레인 fail-closed |
| 4 | `VOICE_STT_SERVICE` (padiem-voice-stt) | 서버 STT | binding transport (`app/voice_stt_routes.py`) | 미구현 — 음성 레인 off 유지 | Tunnel 호스트명 + 대상 proof 검증 + 로컬 클라이언트(PDF와 같은 모양) |
| 5 | `B66_PDF_RENDERER_SERVICE` (padiem-b66-pdf-renderer) | B66 견적서 PDF 렌더 (fetch `/internal/v1/render`) | binding fetch (worker.py:304-337) | **구현 완료** — `LocalB66PdfRendererClient` (같은 경로·키 집합·32MiB 상한·proof) | Tunnel 호스트명 + 대상 proof 검증, env 쌍 |
| 6 | `GOOGLE_OAUTH_STATE_SERVICE` (padiem-google-oauth-state) | workspace connector truth RPC (`workspace_connector_state`) | RPC (`app/connector_workspace_truth.py:218`) | 로그인은 무관하게 동작(§3). **대상 입구 구현(미배포·기본 꺼짐)** — allowlist 1개 | 2와 같은 배포·env 절차 |
| 7 | `P01_ENGINE_SERVICE` (padiem-ai-engine) | P01 웹 XLSX 엔진 호출 (fetch) | binding fetch (`app/web_xlsx_p01_engine_client.py:66-102`) | 미구현 — P01 레인 off 유지 | Tunnel 호스트명 + 호출자 인증 검토 + 로컬 fetch 클라이언트 |
| 8 | `DOCUMENT_PARSER_SERVICE` (padiem-document-parser) | 격리 바이너리 파싱 | transport 존재하나 `wrangler.toml`에서 **주석 처리** | 해당 없음 — 프로덕션에서도 미배선 | 활성화 결정 시 7과 같은 절차 |

원칙: **대상이 HTTP 계약을 이미 가진 것(1·5)** 부터 닫았다. RPC 전용(2·3·6)은
대상의 공개 표면을 새로 만드는 보안 결정이라 이 PR에서 만들지 않았고, Chat 쪽
클라이언트(`HttpRpcBinding`)만 준비했다. 4·7은 로컬 클라이언트가 아직 없고
대상 호스트명도 없어 레인이 꺼진 채로 둔다(현행과 동일).

## 3. Google OAuth — 병행 호스트에서 그대로 동작하게 하는 것

로그인 리다이렉트 URI는 `PADIEM_CHAT_PUBLIC_BASE_URL + "/auth/google/callback"`
(`app/auth.py:322-325`)이고 state 서명은 세션 시크릿 기반이다. 즉 com2에서
`PADIEM_CHAT_PUBLIC_BASE_URL=https://chat-com2.padiem.net`만 두면 코드 변경 없이
동작하며, Google 콘솔에 아래 **값 추가**만 필요하다(대표 작업).

| 콘솔 위치 | 추가할 값 |
|---|---|
| OAuth 2.0 Client ID → 승인된 리다이렉트 URI | `https://chat-com2.padiem.net/auth/google/callback` (정확히 1개) |
| 사용할 클라이언트 | 기존 Web 클라이언트 재사용 여부는 Owner 결정. 새로 만들 경우 `PADIEM_CHAT_GOOGLE_CLIENT_ID`/`_CLIENT_SECRET`을 com2 env에 배치 |
| 승인된 JavaScript 출처 | 불필요 — 서버 리다이렉트 플로우만 사용 |

`GOOGLE_OAUTH_STATE_SERVICE`(workspace truth)가 없으면 §2의 6번 RPC만
fail-closed이고 로그인·세션은 동작한다(https 공개 오리진이므로 `PADIEM_LOCAL_DEV`
불필요).

## 4. 웹 검색 — CPython에서 막히는 원인

런타임 차단이 아니다. `create_web_provider`는 Worker·CPython에서 같은 core
클라이언트를 만들고, CPython에서는 `transport=None`이라 core의 실제 httpx가
쓰인다(`app/web_tools.py:310-332`, `app/httpx_compat.py`). 실제 게이트는 두 개다.

1. 자동 검색은 `runtime_mode=b14`일 때만 켜진다(같은 파일 331행).
2. 키가 필요하다 — Worker는 Secrets Store에서, CPython은 환경변수에서:
   `PADIEM_CHAT_WEB_PROVIDER=tinyfish_daum|tinyfish|daum`,
   `TINYFISH_API_KEY`, `PADIEM_CHAT_DAUM_REST_API_KEY`.

검증: `test_local_cpython.py::test_web_search_is_not_runtime_blocked_on_cpython_only_key_configured`
— 키가 있으면 b14에서 자동 검색 provider가 구성되고, mock/off 기본은 꺼진다.

## 5. 커넥터 WSS — 원인과 순서

- **원인**: 커넥터 게이트웨이는 `worker.py` fetch 선두에서 workerd의 WebSocketPair로
  갈라진다(`worker.py:947-951`, `app/connector_gateway_runtime_mount.py:69-96`,
  `asgi.websocket` 사용). uvicorn ASGI 앱에는 그 레인이 없다. 요청 라우트가 아니라
  런타임 기능이라 uvicorn 설정으로 켤 수 없다.
- **의존**: 이 게이트웨이는 브로커 권한(2번·3번 RPC)과 DO 상태를 전제로 동작한다.
  즉 WSS만 포팅해도 3번이 열리기 전에는 페어링이 완성되지 않는다.
- **대체 설계(순서)**: ① 3번 broker의 HTTPS RPC 표면 → ② Chat CPython에
  starlette WebSocket 라우트를 같은 경로로 추가(`websockets`/uvicorn WS,
  Cloudflare Tunnel은 WS 업그레이드 통과) + `connector_gateway_websocket_session`
  로직 재사용 → ③ PC 커넥터를 chat-com2 호스트로 지정한 실제 페어링 검증.
- 현재: 레인은 워커 전용 그대로 fail-closed(=현행). 죽은 반쪽 구현을 넣지 않는다.

## 6. cron — scheduled 핸들러의 CPython 엔트리

`app/local_cron.py --once`가 컴2 타이머가 부르는 엔트리다. Worker의
`PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED` 게이트를 그대로 평가하고, 실행에
필요한 결속이 없으면 `NOT_CONFIGURED reason=...` 한 줄로 정직하게 끝난다
(종료 코드 0 — 장애가 아니라 미구성).

- 현재 상태: `SKIPPED reason=automation_scheduler_disabled`(기본) 또는
  `NOT_CONFIGURED reason=identity_rpc_unbound`,
  `NOT_CONFIGURED reason=p01_engine_transport_unbound`.
- 실행까지 필요한 것: 2번 identity RPC 표면 + 7번 P01 엔진 HTTPS 클라이언트.
  둘 다 열리면 같은 엔트리에서 실제 tick을 부를 수 있다.
- systemd timer는 배포 꾸러미 PR에서 함께 온다.

## 7. com2 env 계약 (이름만)

| 이름 | 용도 |
|---|---|
| `PADIEM_CHAT_CPYTHON_HOST=1` | com2 병행 호스트 실행 옵트인 — https 공개 오리진 필수, `PADIEM_LOCAL_DEV`와 동시 설정 금지 |
| `PADIEM_CHAT_PUBLIC_BASE_URL=https://chat-com2.padiem.net` | 공개 오리진(https면 local 플래그 불필요) |
| `PADIEM_CHAT_RUNTIME_MODE=mock|b14`, `PADIEM_CHAT_LIVE_ENABLED` | 모델·자동검색 게이트 |
| `B14_UPSTREAM_MODE=https`, `B14_UPSTREAM_URL`, `PADIEM_B14_SERVICE_PROOF_SECRET` | 1번 |
| `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN`, `…_SECRET` | 2번 (클라이언트 준비됨) |
| `PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN`, `…_SECRET` | 5번 |
| `PADIEM_CHAT_WEB_PROVIDER`, `TINYFISH_API_KEY`, `PADIEM_CHAT_DAUM_REST_API_KEY` | 웹 검색 |

시크릿은 env 파일(0600)에만 두고 로그·PR·문서에 값을 적지 않는다.
