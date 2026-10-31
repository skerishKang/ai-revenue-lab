# COM2 호스트 진입점 ↔ 운영 진입점 전수 대조 (2026-10-31)

범위: Chat · 엔진(P01) · 신원기관(control-plane identity) · broker · B14(korean-ai-platform)
기준: `origin/main` = `f6368923d` (#6395 머지 후). #6396(엔진 진입점 교체)·#6398(시험 갱신)은 이 문서 작성 시점에 **미머지**.
방법: 저장소 소스 읽기만. 운영 조회·컴2 서비스 접근·값 출력 없음.

계기: 엔진은 운영 `wrangler.toml`의 `main = "worker_identity.py"`인데 #6385의 호스트 진입점이 레거시 `worker.Default`를 감싸고 있었다(#6396에서 교체). 같은 종류의 불일치가 다른 서비스에 남아 있는지 전수 확인한다.

## 1. 요약

| 서비스 | 운영 진입점 (`wrangler` main) | 컴2 호스트 진입점 | 같은 조립인가 | 판정 |
| --- | --- | --- | --- | --- |
| Chat | `apps/padiem-chat/worker.py` `Default` | `app/local_cpython.py` `build_app()` | 예 — 동일 `create_app`·동일 orchestration composition·동일 write freeze | 다름(바인딩 대역·게이트웨이·scheduled만) |
| 엔진(P01) | `apps/padiem-ai-engine/worker_identity.py` `Default` | `apps/padiem-ai-engine/asgi.py` → `app/local_runtime.py` | **아니오(현재 main)** — 레거시 `worker.Default`를 감싼다 | 다름 → **#6396에서 교체(머지 대기)** |
| 신원기관 | `packages/padiem-control-plane/identity_authority_worker.py` `Default` | `apps/padiem-identity/authority_factory.py` + `com2_identity_rpc_ingress.py` | 예 — 동일 `CanonicalIdentityDurableObject` | 다름(문만 다름, 메서드 부분집합) |
| broker | `packages/padiem-control-plane/local_agent_broker_worker.py` `LocalAgentBrokerDurableObject` | `apps/padiem-broker/service.py` `BrokerComposition` | 예 — 동일 `LocalAgentBrokerDurableRuntime` | 다름(Stage 2-C 부분집합, WSS 없음) |
| B14 | `apps/korean-ai-platform/worker.py` `Default` | `apps/korean-ai-platform/asgi.py` → `app/local_runtime.py` | 예 — 동일 `app.factory.create_app` | 다름(registry 게이트·telemetry 없음) |

## 2. 서비스별 상세

### 2.1 Chat — 같은 앱, 다른 바인딩 대역

같은 것

- 앱 조립: 운영 `Default._build_worker_app`과 호스트 `build_app` 모두 `app.app_factory.create_app`을 쓴다.
- orchestration: 운영은 `app/worker_orchestration.py:283`에서, 호스트는 `app/local_cpython.py:128`에서 같은 `compose_orchestration_bridge`를 호출한다. 켜짐 조건(스위치·`runtime_mode=b14`·D1 상태 저장소)·브리지 클래스가 같다.
- 쓰기 정지: 양쪽 모두 마지막에 `apply_write_freeze`를 적용한다(운영 `worker.py:1758`, 호스트 `local_cpython.py:302`).
- 파일 레인 티켓 시크릿: 운영은 `resolve_secret_binding`, 호스트는 `Settings.from_env`(`app/config.py:423`)로 같은 이름 `PADIEM_CHAT_FILE_LANE_TICKET_SECRET`을 읽는다.

다른 것

| 항목 | 운영 | 컴2 호스트 | 성격 |
| --- | --- | --- | --- |
| D1 | `D1_BINDING_NAME` | `SqliteD1(chat.sqlite3)` | 이전 대상 자체 |
| R2 | R2 바인딩 | `LocalDiskR2` | 이전 대상 자체 |
| Service Binding(identity·B66 PDF·엔진) | Worker 간 호출 | `HttpRpcBinding`·`LocalB66PdfRendererClient`·루프백 엔진 클라이언트(설정 있을 때만, 반쪽 설정은 기동 오류) | 의도된 대역 |
| B14 | Service Binding + proof 시크릿 | `compose_local_b14_transports` | 의도된 대역 |
| connector WSS | `maybe_dispatch_connector_gateway` | `com2_connector_websocket` 게이트웨이, `PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED`일 때만 | 스테이징 전용 별도 구현 — 아래 4.1 |
| `scheduled()` | `run_scheduled_automation_source` | 진입점이 아니라 `deploy/host-com2/cron/` systemd 타이머 | 분리 운영(중복 실행 금지 규칙 필요) |
| Secret Store 조회 | `resolve_web_secrets_store_keys`·`resolve_secret_binding` | 환경변수/파일 | 이전 시 값 주입 경로만 변경 |

### 2.2 엔진(P01) — #6396으로 해소

- 운영: `wrangler.toml:6` `main = "worker_identity.py"`. `worker_identity.Default(legacy_worker.Default)`가 `_engine_services_for_env`로 서비스 레인을 조립한다.
- 현재 main 호스트: `app/local_runtime.create_local_app`이 `import worker` 후 `worker.Default`를 인스턴스화한다(`app/local_runtime.py:537`). 운영과 다른 조립이며, 이 때문에 #6395 왕복 시험이 `run_failed`로 남았다.
- #6396: `create_local_app`이 `worker_identity.Default`를 감싸게 바꾸고, B14 로컬 바인딩 결함 2건(헤더 뷰 변환, `bytes` 응답 스트림)을 함께 고친다. `worker.py`·`worker_identity.py` 수정 0줄.
- 이 문서 PR에서는 중복 수정하지 않는다. #6396 머지 후 엔진 행은 "같음"이 된다.

### 2.3 신원기관 — 같은 권위, 다른 문

- 운영: `identity_authority_worker.py` `Default`는 **Service Binding 전용 게이트웨이**다. 공개 라우트가 없고(`fetch` → 404), `PADIEM_IDENTITY_RPC_INGRESS_SECRET`로 서명된 내부 RPC를 `CanonicalIdentityDurableObject`로 넘긴다.
- 호스트: `apps/padiem-identity/authority_factory.py`가 **같은 `CanonicalIdentityDurableObject`**를 `SqLiteDurableStorage` 위에 조립한다(기존 DB·키 파일 없으면 기동 거부, 스키마 없으면 거부). `packages/padiem-control-plane/com2_identity_rpc_ingress.py`가 `/internal/rpc/{method}`를 연다.
- 같은 것: 권위 클래스·RPC 계약·세션/링크 테이블. 호스트 전용 스키마를 새로 만들지 않는다.
- 다른 것: 호스트 ingress는 12개 메서드(기존 ingress 9 + 커넥터 등록 3)만 허용한다. 운영 게이트웨이가 노출하지만 호스트 allowlist에 없는 메서드 11개:
  `issue_google_connect_ticket`, `create_tenant`, `get_tenant`, `assign_tenant_membership`, `revoke_tenant_membership`, `resolve_active_memberships`, `resolve_active_tenant_membership`, `install_connector_enrollment_schema`, `resolve_connector_owner_scope`, `grant_connector_enrollment_consent`, `revoke_connector_enrollment_consent`.
  Chat의 identity 호출(제품 링크·세션·커넥터 워크스페이스/컨텍스트)은 12개 안에 있어 현재 호출 경로는 막히지 않는다.
- 환경 플래그: `authority_factory.py`가 `CONTROL_PLANE_*` 값을 조립하지만 `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED`는 전달하지 않는다(운영 `wrangler.identity-authority.jsonc`는 `true`). 등록 스키마 설치가 필요해지면 이 값을 명시해야 한다.

### 2.4 broker — 같은 런타임, Stage 2-C 부분집합

- 운영: `local_agent_broker_worker.py` `LocalAgentBrokerDurableObject`(DO) + `route_private_pc_wss_upgrade` WSS.
- 호스트: `apps/padiem-broker/service.py` `BrokerComposition`이 같은 `LocalAgentBrokerDurableRuntime`·디바이스 HTTP·텍스트/오피스/프로필 스토어를 `SqLiteDurableStorage` 위에 조립하고 `/internal/rpc/{method}` allowlist 24개를 연다. proof secret·pepper 없으면 기동 거부.
- 같은 것: RPC 메서드 구현(재구현 없음, 위임만), proof 검증.
- 다른 것: ① WSS 업그레이드 라우트 없음 ② 큐 소유 dispatch(`poll`/`admit`/`enqueue_command`/`reconcile`) 의도적 제외 ③ DO storage API 대신 SQLite 어댑터. ②는 설계상 제외이고, ①은 #5115 10-30 보류 기록의 미완성 항목(broker RPC·WebSocket)과 같은 자리다.

### 2.5 B14 — 같은 앱 팩토리, 호스트에 없는 두 게이트

- 운영 `Default.fetch`: `/` → 307 `/workspace`, `ensure_private_registry` 실패 시 503, request-scoped env·ledger·deferred writes, 보안 헤더, `/api/pilot|/api/b66` stack telemetry.
- 호스트 `create_local_app`: `app.factory.create_app()` + `LocalRequestScopeMiddleware`(env 바인딩·ledger·deferred writes·보안 헤더) + `/` → 307 `PRODUCT_ENTRY_PATH`.
- 같은 것: 앱 팩토리, 루트 307, 보안 헤더, 요청 범위 격리, ledger 핸들 취급.
- 다른 것: ① `ensure_private_registry` 호출이 `app/local_runtime.py`·`app/factory.py`에 없다(운영은 모델 카탈로그 진입 전에 호출) ② `/api/pilot`·`/api/b66` stack telemetry 없음. ①은 호스트에 R2 기반 private registry 바인딩이 없어 단순 호출 추가로 해결되지 않는다.

## 3. 이 PR에서 고친 것

없음. 진입점 수준에서 "작고 명확한" 불일치는 엔진 한 건뿐이고, 그 수정은 #6396이 이미 담고 있다(이 PR과 같은 파일을 건드려 충돌만 만든다). 나머지는 바인딩 대역·범위 결정·미구현 기능이라 문서로만 남긴다. 운영 Worker 코드는 수정하지 않았다.

## 4. 남은 차이와 다음 작업

### 4.1 Chat connector WSS — 호스트 구현이 운영과 다른 코드

운영은 `maybe_dispatch_connector_gateway`, 호스트는 `com2_connector_websocket`(스테이징 전용, 루프백 identity `8802`·broker `8799` RPC). 같은 WSS 경로·같은 하위 RPC 메서드 집합을 쓰지만 게이트웨이 본체가 다르다.
다음: 운영 전환 전에 호스트 게이트웨이가 운영 게이트웨이와 같은 검증(edge proof·replay DB·메서드 allowlist)을 하는지 차동 시험 1건. 별도 PR.

### 4.2 신원기관 메서드 11개

필요해지는 호출이 생길 때만 allowlist에 추가한다. 지금 추가하면 검증되지 않은 표면을 넓힌다.
다음: Chat 호출부 전수 확인 후 필요한 것만 추가(별도 PR). `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED` 전달도 같은 PR.

### 4.3 broker WSS

`route_private_pc_wss_upgrade`에 해당하는 호스트 라우트가 없다. PC 커넥터 WebSocket이 Cloudflare에 남아 있는 동안은 문제가 없고, 큐·브로커 이전 마지막 단계에서 필요하다.
다음: #5573 잔여 항목(broker RPC·WebSocket) 안에서 처리.

### 4.4 B14 private registry 게이트

호스트가 모델 카탈로그를 어떤 경로로 읽는지에 달려 있다. registry 바인딩을 호스트에 만들지 않으면 게이트를 그대로 옮길 수 없다.
다음: 컴2 B14 `b14.env`의 카탈로그 출처 확인 후, 필요하면 호스트 전용 registry 대역 1건.

## 5. 확인 상태

- 저장소 소스 읽기만 수행했다. 운영 Worker·컴2 서비스·Cloudflare 계정 조회는 하지 않았다.
- #6396·#6398은 미머지이므로 엔진 행은 #6396 머지 시점에 "같음"으로 바뀐다.
- 컴2에서 실제로 어떤 진입점 파일이 기동 중인지는 확인하지 않았다(`deploy/host-com2/*` 유닛이 가리키는 모듈 기준).
