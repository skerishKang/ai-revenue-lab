# B14 COM2 실행 Runbook — Workers 없이 올리기 (#5784)

기준: `docs/architecture/COM2_MIGRATION_INVENTORY_20261025.md` §2.2·§4.1·§4.2의 `ai-revenue-korean-ai-platform` 행(Secrets Store 16개 이름, D1·R2·KV 미선언, 게이트 목록).
자산: `deploy/host-com2/b14/` + `apps/korean-ai-platform/asgi.py` · `app/local_runtime.py` · `b14.env.example`.
디렉터리 이름은 `com2`가 아니라 `host-com2`다: 경로 구성요소가 정확히 `com2`인 디렉터리는 Windows 예약 장치 이름이라 git for Windows가 기본 설정(`core.protectNTFS`)에서 인덱싱을 거부하고 일반 Windows 파일 API로도 열리지 않는다. 이 저장소는 Windows PC에서 다루므로 모든 플랫폼에서 읽히는 이름으로 두었다. 호스트 안의 실제 경로는 계속 `/opt/padiem/...`와 `padiem-b14.service`다.
**이 문서와 파일들의 등록은 설치·기동·전환·배포를 뜻하지 않는다.** 각 단계는 아래 권한 소유자가 별도 승인 아래 실행한다.

## 누가 무엇을 하는가

| 단계 | 실행 주체 | 이 저장소가 하는 일 / 하지 않는 일 |
| --- | --- | --- |
| 1 설치(스테이징) | **컴2 아스트라** | `install.sh`를 읽어 확인 후 실행. 리포지토리는 유닛·드롭인·logrotate·ingress 템플릿만 제공한다 |
| 2 키 입력 | **Owner** | 값은 이 저장소·로그·PR·문서에 전혀 등장하지 않는다. 이름 목록만 `b14.env.example`에 있다 |
| 3 기동·헬스 | **컴2 아스트라** | `systemctl start`는 아스트라만이 한다. 이 저장소 어떤 스크립트도 enable/start 하지 않는다 |
| 4 상류 전환 | **게이트** | `B14_UPSTREAM_MODE`·`B14_UPSTREAM_URL` 설정과 Chat/Engine 재배포. 코드 배포 게이트 절차 따름 |
| 5 복귀 | **게이트** | 변수를 `binding`으로 되돌리고 재배포. 잔여 상태 없음(스위치는 런타임 갱신 없음) |

## Step 1 — 설치(스테이징) — 컴2 아스트라

레이아웃: 앱 체크아웃 `/opt/padiem/b14/app`(여기에 `asgi.py`), venv `/opt/padiem/b14/venv`, 이 묶음 사본 `/opt/padiem/b14/deploy`.

```bash
bash /opt/padiem/b14/deploy/host-com2/b14/install.sh --dry-run
bash /opt/padiem/b14/deploy/host-com2/b14/install.sh --reload
```

기대 마커: `B14_COM2_INSTALL=staged:unit`, `already_current:*`, `NO_SERVICE_STARTED=YES`, `NO_CREDENTIAL_WRITTEN=YES`.
거부 마커(그대로 멈추고 CENTRAL에 보고): `B14_COM2_INSTALL_ABORT=foreign_target:unit|asgi_entry_missing|venv_python_missing|root_required|linux_required`.
공유 cloudflared 설정이 이미 있으면 이 스크립트는 덮어쓰지 않고 `ingress_add_manual_required:hostname=b14.padiem.net`만 알림 → 아래 Step 3-나.

## Step 2 — 키 입력 — Owner

`/opt/padiem/b14/secrets/` 아래에 **바인딩 이름 그대로** 파일 하나씩(0600), 또는 Unit이 읽는 `/opt/padiem/b14/env/b14.env`에 직접 기입. 대상 이름은 §2.2 목록과 동일:

`PADIEM_B14_CREDENTIAL_01` … `PADIEM_B14_CREDENTIAL_14`, `PADIEM_B14_SERVICE_PROOF_SECRET`, `PADIEM_GRAFANA_OTLP_TOKEN`.

- 값 복사·스크린샷·PR 게시 금지. 확인은 존재·권한만으로: `stat -c '%a %n' /opt/padiem/b14/secrets/*`.
- 그룹·타인 읽기 가능한 파일은 앱이 **거부**하고 그 라인은 실패로 닫힌다(값 노출 대신).
- Cloudflare 자격증명을 이 PC로 옮기지 않는다. Owner가 새 값을 입력한다.

## Step 3 — 기동·헬스 — 컴2 아스트라

```bash
systemctl start padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

기대: `{"healthy": true, "exit_code": 0, "issues": [], "observed": {"app": "korean-ai-platform", ...}}` — `demo_mode`이 `true`면 healthy로 보지 않는다(`issues:["demo_mode_true"]`).
3-a. 파일 로그를 원하면 `20-log-to-file.conf.example` 드롭인 + `logrotate.conf.example` 설치 후 `logrotate --debug --state /dev/null /etc/logrotate.d/padiem-b14`. 기본은 journald 수집이다.
3-b. Tunnel 공존: `/opt/padiem/cloudflared/config.yml`에 `b14.padiem.net → http://127.0.0.1:8789` 항목을 **추가**하고(파일 레인 `files.padiem.net:8788`과 한 파일 공존, catch-all `http_status:404`는 항상 마지막) `cloudflared tunnel --config <file> ingress validate`로 오프라인 검증 후 재시작. hostname 충돌이면 덮지 말고 중단.

## Step 4 — 상류 전환 — 게이트

Switch는 두 개의 이름뿐이다(PR-2 `padiem_ai_core/b14_upstream.py`가 판정):

```
B14_UPSTREAM_MODE=binding   # 기본값. 지금과 동일한 Service Binding 구성
B14_UPSTREAM_MODE=https + B14_UPSTREAM_URL=https://b14.padiem.net
```

- 확인 순서: B14 단독 health → B14 증명 필요 라인이 401/503이 아니라 응답 → Chat·Engine 각각 `binding`으로 한 번, `https`로 한 번 → 동일 모델·동일 스트리밍 계약 확인.
- 전환은 재배포 행위이므로 코드 배포 게이트 절차를 따른다. 이 runbook은 전환을 승인하지 않는다.
- 확인된 동작: **Engine도 Workers에 남아 있는 동안 `https` 레인을 시작한다**(#5902). 전용 전송체 `CloudflareB14UpstreamTransport`가 Worker fetch를 타고 `MAX_POST_BODY_BYTES = None`으로 모델 요청을 끝까지 실어 보내고, 제3자 엔드포인트를 향하는 일반 외부 fetch 경로의 8,192B POST 상한은 그대로다. 기존의 시작 거부(`b14_upstream_https_requires_a_worker_fetch_transport`)는 폐기됐다.

## Step 5 — 복귀 — 게이트

`B14_UPSTREAM_MODE`를 제거(또는 `binding`)하고 `B14_UPSTREAM_URL`도 비운 뒤 재배포. 반쪽 상태(`URL`만 남김)는 `b14_upstream_url_ignored_in_binding_mode`로 시작이 거부되므로, 복귀는 두 변수를 함께 비워야 완료된다. 스위치에 캐시·저장 상태·런타임 갱신 경로가 없어 이전 동작으로 되돌아간다.

## 금지·경계

- 이 저장소에서 Secret·Binding·D1 설정을 변경하거나 Cloudflare 자산을 생성/삭제하지 않는다.
- `scripts/ops/com2_tunnel.py`의 `PUBLIC_SERVICES`를 확장해 b14를 강제로 공개하지 않는다(두 커밋된 테스트가 고정하는 계약). 위 ingress는 운영자 설정 파일에 별도 항목으로 추가한다.
- 장부 SQLite·로그는 `/opt/padiem/b14/{ledger,logs}`. 로테이션: `daily`·`rotate 7`·`maxsize 50M`·`copytruncate`.
- 실PC Connector·#4434 Excel·알림 레인 코드와는 무관한 파일만 다룬다.

관련: #5784(이 작업) · #5115(COM2 이전 추적) · #5881/#5891/#5892(파일 레인·Tunnel 준비) · `docs/operations/COM2_HOST_FACTS_20261026.md`
