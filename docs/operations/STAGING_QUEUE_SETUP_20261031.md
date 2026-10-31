# COM2 스테이징 큐 구축 (#6305, 2026-10-31)

상태: 로컬 loopback 구축·검증 완료. Cloudflare Tunnel·DNS·origin 등록과 스테이징 Worker E2E는 하지 않았다. 운영 큐·실행기·파일 레인·cloudflared·lovetree-api는 변경·재시작하지 않았다.

## 결정

| 항목 | 값 | 근거 |
|---|---|---|
| 포트 | `127.0.0.1:8830` | 8790은 `lovetree-api.service`가 점유. 8830은 WSL·Windows 모두 비어 있고 문서·계획에 없음. 예비 `8831` |
| DB | `/opt/padiem/mesh-queue-staging/queue.db` | 운영 `queue.sqlite3`와 분리 |
| 유닛 | `padiem-mesh-queue-staging.service` | 운영 유닛과 분리, 부팅 자동 시작 안 함(disabled) |
| 시크릿 | 스테이징 전용 새 값 2개 | 운영 시크릿과 분리, 값은 기록·출력하지 않음 |

포트 조사(2026-10-31): WSL `ss -ltnp`에서 87xx/88xx를 쓰는 것은 8788(file-lane), 8790(lovetree-api), 8797(mesh queue)뿐이었다. Windows `Get-NetTCPConnection -State Listen`에서 8788/8790/8797은 `wslrelay` 포워딩, 8791·8820~8824는 개발용 `dev-auth-chain`, 8899는 로컬 `workerd`였다. Windows 제외 대역(`netsh int ipv4 show excludedportrange protocol=tcp`)에 8830·8831은 없고, WSL ephemeral 범위는 32768–60999다.

## 격리 경계

| 항목 | 운영 | 스테이징 |
|---|---|---|
| 루트 | `/opt/padiem/mesh-queue` | `/opt/padiem/mesh-queue-staging` |
| 유닛 | `padiem-mesh-queue.service` | `padiem-mesh-queue-staging.service` |
| 포트 | `127.0.0.1:8797` | `127.0.0.1:8830` |
| DB | `queue.sqlite3` | `queue.db` |
| 시크릿 | `/opt/padiem/mesh-queue/*.txt` | `/opt/padiem/mesh-queue-staging/*.txt` (새 값) |
| 코드 | 운영 루트 + `src` 링크 | 운영 루트와 무관한 복사본 |
| 실행기 | 운영 실행기 | 없음(합성 전용, 미구성) |
| Tunnel/DNS | `queue.padiem.net` | 없음(등록하지 않음) |

`app/`, `padiem_ai_core/`, `padiem_control_plane/`는 운영 루트의 심볼릭 링크를 따라가지 않고 스테이징 루트로 복사했다. `service.py`·`schema.py`·`internal_store.py`는 운영과 동일 내용의 복사본이다(해시 동일). 포트 차이는 `serve_staging.py` 한 파일에만 있다.

## 구축 방법 (실행한 순서)

1. 디렉터리: `install -d -m 0700 -o padiem-mesh -g padiem-mesh /opt/padiem/mesh-queue-staging`
2. 코드 복사: 운영 루트에서 `service.py`, `schema.py`, `internal_store.py`, `requirements.txt`; 저장소 사본에서 `app/`, `padiem_ai_core/`, `padiem_control_plane/`, `migrations/`(78개).
3. venv: 운영 venv를 `cp -a`로 복사했다. 패키지 설치·네트워크 접근 없음. `sys.prefix`가 스테이징 venv임을 확인했고 `starlette 0.46.2`·`uvicorn 0.51.0`을 그대로 사용한다.
4. 런처 `serve_staging.py`:
   ```python
   import uvicorn

   from service import app_from_environment

   if __name__ == "__main__":
       uvicorn.run(app_from_environment(), host="127.0.0.1", port=8830, log_level="warning")
   ```
5. `queue.env`(0600) — 경로만:
   ```
   MESH_QUEUE_DB_PATH=/opt/padiem/mesh-queue-staging/queue.db
   MESH_QUEUE_CHANNEL_SECRET_FILE=/opt/padiem/mesh-queue-staging/channel-secret.txt
   MESH_QUEUE_SERVICE_SECRET_FILE=/opt/padiem/mesh-queue-staging/service-secret.txt
   MESH_QUEUE_MIGRATIONS_DIR=/opt/padiem/mesh-queue-staging/migrations
   MESH_QUEUE_LEGACY_MAP_LANE=off
   MESH_QUEUE_REQUEST_LOG=refusals
   MESH_QUEUE_EXECUTION_MODE=mesh
   PYTHONPATH=/opt/padiem/mesh-queue-staging
   PATH=/opt/padiem/mesh-queue-staging/venv/bin:/usr/local/bin:/usr/bin:/bin
   ```
6. 시크릿 2개를 새로 생성했다(값 출력·기록 없음). `head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n'`로 96바이트 hex, `chmod 600`, owner `padiem-mesh`:
   - `/opt/padiem/mesh-queue-staging/channel-secret.txt`
   - `/opt/padiem/mesh-queue-staging/service-secret.txt`
7. 유닛 작성 → `systemctl daemon-reload` → `systemctl start padiem-mesh-queue-staging.service` (enable 안 함).

첫 시작은 마이그레이션 경로를 찾지 못해 실패했다(`queue migration missing: /opt/padiem/padiem-chat/migrations/...`). `migrations/` 복사와 `MESH_QUEUE_MIGRATIONS_DIR` 지정 후 재시작해 성공했다.

## 유닛 (값 없음)

```ini
[Unit]
Description=Padiem #6305 staging PC dispatch queue (isolated 127.0.0.1:8830)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=padiem-mesh
Group=padiem-mesh
EnvironmentFile=/opt/padiem/mesh-queue-staging/queue.env
ExecStart=/opt/padiem/mesh-queue-staging/venv/bin/python serve_staging.py
WorkingDirectory=/opt/padiem/mesh-queue-staging
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
Restart=always
RestartSec=10
TimeoutStartSec=30
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

`UnitFileState=disabled` — 부팅 자동 시작은 하지 않는다. 수동 `systemctl start padiem-mesh-queue-staging.service`.

## 인증·권한 경계

- `MESH_QUEUE_LEGACY_MAP_LANE=off`이므로 `RETIRED_OWNERSHIP_MAP`(authorizes nobody)으로 조립된다. 실제 PC 대상이 없고, 합성 실행기 연결도 아직 하지 않았다.
- 채널 시크릿과 서비스 시크릿은 스테이징 전용 새 값이다. 운영 큐의 시크릿 파일을 읽지 않는다.
- 시크릿 값은 이 문서·저장소·로그·보고에 기록하지 않는다. 보관 경로만 위에 적었다.

## 실측값 (2026-10-31 09:36 KST)

| 항목 | 값 |
|---|---|
| 유닛 | `ActiveState=active`, `SubState=running`, `MainPID=2976223`, `UnitFileState=disabled` |
| 시작 로그 | 성공한 시작(09:36:59) 이후 오류 없음 |
| 리스너 | `127.0.0.1:8830` (`python`, pid 2976223) |
| `/health` 8830 | `{"ok":true,"queue":"mesh","pending_unclaimed":0,"pending_claimed":0,"received":0}` |
| `/health` 8797 (운영) | `{"ok":true,"queue":"mesh","pending_unclaimed":0,"pending_claimed":0,"received":0}` (구축 전과 동일) |
| `/health` 8788 (파일 레인) | `{"ok":true}` (구축 전과 동일) |
| 8790 (lovetree-api) | `{"error":{"code":"unauthenticated",...}}` (구축 전과 동일) |
| 운영 유닛 | queue·executor·file-lane·cloudflared·lovetree-api 모두 `active` 유지 |
| DB | `oracle_mesh_dispatch` 0행, `queue_schema_applied` 9행, 테이블 5개 |
| 시크릿 파일 | `channel-secret.txt`·`service-secret.txt` 각 mode 600, owner `padiem-mesh:padiem-mesh`, 96 bytes |

코드 해시(스테이징=운영):

```
c6830bcdfc6e7830e847cfdfed3dafb24242401e87889c6547c3184bba239005  service.py
3759d3668f29bb45de0652d49f7c57307409fd8f303e32e0dfb0ef5618570b3f  schema.py
8e7d66511c003d344f1275a9167b27e3d0c2a0bd8443f7bf60d47d7e72f0b66b  internal_store.py
```

## 포트 확인 방법

```bash
# WSL
ss -ltnp | grep -E ':(8830|8831) '        # 출력 없으면 비어 있음

# Windows
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8830,8831 }
netsh int ipv4 show excludedportrange protocol=tcp
```

문서·계획 충돌은 저장소에서 `\b(87[0-9]{2}|88[0-9]{2})\b`로 검색해 확인한다. 8830·8831은 현재 문서에 없다.

## 하지 않은 것

- Cloudflare Tunnel·DNS·origin 등록 없음.
- 운영 서비스 변경·재시작 없음.
- 실제 PC·운영 실행기 연결 없음.
- 시크릿 값 출력·기록 없음.
- 부팅 자동 시작(enable) 없음.
- 기존 파일 삭제 없음(백업이 필요하면 새 이름 사용).

## 롤백 (실행하지 않음)

```bash
systemctl stop padiem-mesh-queue-staging.service
# 필요 시: systemctl disable padiem-mesh-queue-staging.service
```

파일은 삭제하지 않고 보존한다. 운영 큐·DB·유닛과 무관하므로 운영에는 영향이 없다.

## 남은 작업

- 합성 실행기 연결(별도 지시). 그때 스테이징 채널 시크릿을 소비자에게 안전하게 전달한다(값은 파일에서 직접 읽고 인자·로그에 남기지 않음).
- Cloudflare Tunnel·DNS·origin 등록은 CTO 승인 후 별도 작업.
- 스테이징 Worker E2E는 #6296/#6282 경로 확정 후.
