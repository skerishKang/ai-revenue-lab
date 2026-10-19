# COM2 기본 런타임 감독·Tunnel 경로 (2026-10-19)

- 결정/추적: [#5115](https://github.com/skerishKang/ai-revenue-lab/issues/5115)
- 상위 계획: `docs/operations/COM2_PRIMARY_CLOUDFLARE_SECURITY_BACKUP_ARCHITECTURE_20261019.md`
- 구현: `scripts/ops/com2_runtime.py`, `scripts/ops/com2_tunnel.py`
- 상태: **SUPERVISOR_IMPLEMENTED / TASK_REGISTERED / LOCAL_LIVE_VERIFIED / TUNNEL_RENDER_AND_OFFLINE_VALIDATE / CUTOVER_NOT_EXECUTED**

## 원칙

COM2는 업무 실행의 정본이고 Cloudflare는 DNS·TLS·WAF·DDoS·Bot·Tunnel·R2 백업을 담당한다. 이번 구현은 기존 실행 코드를 그대로 재사용하고, 그 위에 빠져 있던 **상태 확인·자동 시작·제한적 재시작·Tunnel ingress 렌더링**만 추가한다.

- 서비스 코드, 모델 라우팅, 인증·세션 로직은 변경하지 않는다.
- 공개 리스너를 새로 만들지 않는다. 모든 서비스는 `127.0.0.1`에만 바인딩된다.
- Cloudflare DNS·운영 트래픽·Tunnel token·Worker·D1·R2·Secret은 이 작업에서 변경하지 않는다.
- LOCAL A 데이터·백업 파일을 수정하지 않는다.

## 재사용한 기존 자산

| 구성 | 기존 경로 | 역할 |
|---|---|---|
| B14 Router | `infrastructure/start-b14-release.ps1` | 127.0.0.1:18717, DPAPI secret-store 경유 실행 |
| Chat·Claw API | `b62-chat-api/start-b62-release.ps1` | 127.0.0.1:18764, B14 런타임 연결 |
| P01 Engine | `p01-ai-engine/start-p01-local.ps1` | 127.0.0.1:18731, 내부 실행 경계 |
| 시작 스크립트 묶음 | `infrastructure/start-local-ai.ps1` | OnLogon·Watchdog 작업이 5분마다 호출 |
| 스케줄러 | `PADIEM-Local-AI-OnLogon`, `PADIEM-Local-AI-Watchdog` | Interactive / Limited, 사용자 로그온 세션 |
| 백업 스케줄 | `PADIEM-COM2-D1-R2-Sync` | 매일 04:20 D1/R2 동기화 |

새 감독기는 시작 스크립트를 복제하지 않고 직접 호출한다. 기존 Watchdog는 "포트가 없으면 시작"만 수행하므로, 감독기는 **포트가 있어도 계약이 깨진 경우**와 **시작 후 준비 실패**를 다룬다.

## 구성 요소와 제품 표면

| 구성 요소 | 종류 | 포트 | 계약 확인 |
|---|---|---|---|
| b14 | HTTP | 18717 `/health` | `status=ok`, `app=korean-ai-platform` |
| b62 | HTTP | 18764 `/health` | `status=ok`, `app=padiem-chat`, `runtime=b14` |
| p01 | HTTP | 18731 `/internal/v1/health` | `status=ok`, `service=padiem-ai-engine`, completed/streaming 지원, non-health identity 필수 |
| b66 | source/library | 없음 | `b66-quote-adapter`, `b66-pdf-renderer` 소스 존재 |

제품 매핑:

```text
chat  -> b62
claw  -> b62 (Claw Connector는 클라이언트이며 COM2 상주 서버가 아님)
engine-> p01 (내부 전용)
quote -> b66 source/library (현재 로컬 HTTP 라우트 없음)
```

B66는 Worker PDF 렌더러와 quote adapter 라이브러리로 존재한다. 로컬 HTTP 서버가 없으므로 감독기가 B66 포트를 만들거나 Tunnel에 매핑하지 않는다. B66를 COM2에서 공개 서비스로 운영하려면 먼저 로컬 HTTP 경계를 추가해야 한다.

## 감독기 명령

```powershell
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py status
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py ensure
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py verify
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py restart b62
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py stop b62
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py install-task --dry-run
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py install-task --force
```

- `status`: 읽기 전용. 리스너, HTTP 상태, 계약 필드, loopback 여부, 관리 여부를 JSON으로 출력한다.
- `ensure`: 이미 정상인 구성 요소는 건드리지 않는다. 리스너가 없으면 기존 시작 스크립트로 시작하고, 자기가 시작한 PID를 `.com2-runtime/managed.json`에 기록한다. 감독기가 시작하지 않은 리스너는 unhealthy여도 종료하지 않는다.
- `restart`: 감독기가 기록한 PID만 `taskkill /T /F`로 재시작한다. 기록이 없으면 `not_supervised`로 거부한다.
- `stop`: 감독기가 기록한 PID만 종료한다.
- `verify`: HTTP 서비스의 계약·loopback 증거와 제품 준비 상태를 확인한다. B66는 `library_only`로 명시한다.
- `install-task`: `PADIEM-COM2-Runtime-Supervisor` 작업을 등록한다. 기존 Watchdog와 같은 Interactive/Limited 계정이며, 5분 주기 시작 시각을 00:01로 두어 기존 Watchdog(11:42 기준 5분 주기)와 충돌을 줄인다. `--force`는 같은 이름의 기존 작업을 교체한다.
- 작업 launcher는 `py -3 com2_runtime.py ensure`를 실행하고, 실패한 경우에만 제목·종료 코드와 출력을 `.com2-runtime/supervisor.log`에 남긴다. 정상 실행은 `status.json`으로 확인한다.

안전 장치:

- 단일 인스턴스 lock(`.com2-runtime/supervisor.lock`, 10분 stale).
- 상태 파일 원자적 교체(`status.json`, `managed.json`).
- 자동 재시작은 감독기 관리 PID에 한정하고 300초 cooldown을 둔다.
- 로그는 `.com2-runtime/logs/<component>.log`에만 기록하며 Secret 값을 출력하지 않는다.
- 상태 JSON에는 PID·포트·계약 boolean만 포함하고 Secret·고객 데이터를 넣지 않는다.

## Tunnel ingress

Tunnel은 공개 진입점만 담당한다. 렌더러는 명시적 `SERVICE=HOSTNAME` 매핑만 받고, origin은 고정 loopback URL만 허용한다.

```powershell
py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_tunnel.py render `
  --map chat=chat.example.com --map claw=claw.example.com `
  --tunnel-name com2-primary --output D:\PADIEM-Servers\.com2-runtime\cloudflared-ingress.yml

py -3 D:\padiem-cloudflare-com2\scripts\ops\com2_tunnel.py validate `
  --config D:\PADIEM-Servers\.com2-runtime\cloudflared-ingress.yml
```

- 공개 매핑 가능: `chat`, `claw` (127.0.0.1:18764).
- 내부 전용: `b14`(18717), `p01`(18731). 공개 매핑 시 `internal_service_not_public`로 거부한다.
- 마지막 규칙은 항상 `http_status:404`.
- SSE/NDJSON을 위해 `disableChunkedEncoding: false`, `connectTimeout: 30s`, `tcpKeepAlive: 30s`.
- `validate`는 `cloudflared tunnel --config <file> ingress validate`를 실행하는 오프라인 검사다.
- 렌더러는 token·credentials 파일·DNS 레코드를 만들지 않는다. 활성화는 별도 운영 절차다.

활성화 전 필요한 것:

1. 실제 공개 hostname과 Cloudflare Tunnel 이름/자격 증명 소유자 확인.
2. WAF·Access·rate limit 정책을 기존 운영과 동일하게 적용할지 결정.
3. `cloudflared`를 Windows 서비스 또는 Task Scheduler로 등록할지 결정.
4. B62의 인증·canonical identity·history store 바인딩 상태 확인. 현재 `/health`는 `auth_configured=false`, `canonical_identity_bound=false`, `history_store_bound=false`를 보고한다.
5. 제품별 세션·권한 경계 검증 후 트래픽 전환.

## 2026-10-19 COM2 로컬 검증

실행 위치: COM2 `D:\PADIEM-Servers`, 최신 main 기준 `feat/com2-primary-runtime-5115` 브랜치.

```text
status            healthy=true
b14               listening=true health=true contract=true loopback_only=true
b62               listening=true health=true contract=true loopback_only=true
p01               listening=true health=true contract=true loopback_only=true
b66               library ready=true, http_listener=false
products          chat=ready claw=ready engine=ready quote=library_only
ensure            모든 구성 요소 already_healthy, 시작·종료 없음
verify            passed=true
tunnel render     chat/claw -> 127.0.0.1:18764, catch-all 404
tunnel validate   exit=0, "Validating rules ... OK", network_used=false
task register     PADIEM-COM2-Runtime-Supervisor, Interactive/Limited, 5분 주기
task first run    schtasks /Run -> LastTaskResult=0
launch path       임시 fake b62: started -> contract=true -> managed PID 기록 -> stop -> port closed
parent exit       시작 프로세스 종료 후에도 서비스 생존 확인, 감독기 stop으로 종료
```

실행 중인 B14·B62·P01은 모두 `managed=false`로 표시되며, 감독기는 이들을 재시작하지 않았다. 실제 서비스 시작 경로는 임시 디렉터리의 fake 서비스로만 검증했고 운영 서비스에는 적용하지 않았다.

이 검증은 실행 중인 프로세스를 재시작하지 않았다. 기존 서비스는 감독기 관리 대상이 아니므로 `managed=false`, `unmanaged_unhealthy_untouched` 정책이 적용된다. 감독기 관리 경로는 로컬 테스트에서 가짜 서비스로 검증했다.

## 변경하지 않은 것

- Cloudflare 운영 Worker, DNS, route, Tunnel token, WAF 설정.
- 운영 D1, R2 객체, Secret.
- LOCAL A의 데이터·Secret·백업 파일.
- 기존 OnLogon/Watchdog 작업과 `start-local-ai.ps1`.

## 롤백

```powershell
schtasks /Delete /TN PADIEM-COM2-Runtime-Supervisor /F
Remove-Item D:\PADIEM-Servers\.com2-runtime -Recurse
```

감독기가 시작한 서비스가 남아 있으면 `stop <component>`로 먼저 종료한다. 감독기 관리 기록이 없는 서비스는 기존 시작 스크립트·작업으로 계속 운영된다.
