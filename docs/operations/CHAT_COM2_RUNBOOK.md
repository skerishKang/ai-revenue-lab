# COM2 Chat 병행 운영 호스트 런북 (chat-com2.padiem.net)

```text
DOC_ROLE=CHAT_COM2_RUNBOOK
STATUS=꾸러미·러닝북 준비 완료 / 설치·기동은 Qoder가 컴2에서 수행
RELATED=deploy/host-com2/chat/, docs/architecture/COM2_CHAT_SERVICE_BINDINGS_20261029.md
경계: chat.padiem.net(Cloudflare 프로덕션)의 Worker·터널·DNS는 건드리지 않는다.
```

## 0. 전제

- 컴2는 Linux, `/mnt/d`는 마운트된 데이터 디스크(파일 레인과 동일 규약).
- `deploy/host-com2/chat/install.sh`는 **아무것도 시작·활성화하지 않는다**.
- 공개는 Cloudflare Tunnel(chat-com2 전용 터널)로만. 앱은 `127.0.0.1:8798` loopback.

## 1. 설치 (Qoder)

```bash
# 재료 확인 + 변경 계획만
bash deploy/host-com2/chat/install.sh --dry-run

# 실제 설치(서비스는 시작하지 않음)
sudo bash deploy/host-com2/chat/install.sh --apply
```

설치가 하는 일: `padiem-chat` 계정 → `/opt/padiem/chat-com2`(+venv, 핀된 requirements)
→ 모듈 symlink(app, padiem_ai_core, padiem_control_plane, kagent — 단일 소스)
→ `.env`(0600, example 복사) → 서비스 사용자 권한 프로브 → **import 스모크**
→ systemd 유닛 5개 설치 + daemon-reload. 실패는 `CHAT_COM2_INSTALL=<사유>`로 멈춘다.

## 2. env 채우기

`/opt/padiem/chat-com2/.env`(0600)에 값 입력. 이름·의미는
`docs/architecture/COM2_CHAT_SERVICE_BINDINGS_20261029.md` §7.
최소 기동: `PADIEM_CHAT_AUTH_MODE`, `PADIEM_CHAT_SESSION_SECRET`(≥32자),
`PADIEM_CHAT_PUBLIC_BASE_URL=https://chat-com2.padiem.net`.
B14를 켤 때만: `PADIEM_CHAT_RUNTIME_MODE=b14`, `B14_UPSTREAM_MODE=https`,
`B14_UPSTREAM_URL`, `PADIEM_B14_SERVICE_PROOF_SECRET`(Owner 승인 엔드포인트).

검증: `sudo -u padiem-chat /opt/padiem/chat-com2/venv/bin/python /opt/padiem/chat-com2/check_config.py`
→ `CHAT_COM2_CONFIG_READY=1`.

## 3. 기동·터널

```bash
sudo systemctl start padiem-chat-com2.service
systemctl status padiem-chat-com2.service --no-pager
sudo -u padiem-chat /opt/padiem/chat-com2/venv/bin/python \
  /opt/padiem/chat-com2/health.py --url http://127.0.0.1:8798/health   # CHAT_COM2_HEALTH=PASS
```

터널: `cloudflared-chat-com2.example.yml`을 `/etc/cloudflared/`에 복사해 UUID·자격증명
경로를 채우고 chat-com2 전용 cloudflared 인스턴스로 띄운다(**chat.padiem.net 터널
설정과 파일을 공유하지 않는다**). 이후 `https://chat-com2.padiem.net/health`가
`{"status":"ok"}`이면 공개 경로 완료.

타이머(원할 때만): `systemctl enable --now padiem-chat-com2-health.timer
padiem-chat-com2-backup.timer`. 백업은 `VACUUM INTO` → 사본 integrity_check·행 수
검증 통과 후에만 rotate(`/mnt/d/padiem/chat-com2/backups`, 7개 유지).
자동화 cron 엔트리: `/opt/padiem/chat-com2/venv/bin/python -m app.local_cron --once`
(`NOT_CONFIGURED reason=…`이면 §서비스 바인딩 표의 미결 항목이 원인).

## 4. Google 로그인

`PADIEM_CHAT_GOOGLE_CLIENT_ID/SECRET` 배치 + Google 콘솔에
`https://chat-com2.padiem.net/auth/google/callback` 리다이렉트 URI 추가(대표 작업,
값 목록은 서비스 바인딩 문서 §3). 코드·state 서명 변경 없음.

## 5. 데이터 — 병행 운영은 D1을 쓰지 않는다

- 처음엔 빈 SQLite + 마이그레이션 001~077 자동 적용(부팅 시, 자체 장부).
- D1 → SQLite 전체 복사는 **준비만** 되어 있다: `apps/padiem-chat/copy_state.py`
  (`copy --source <D1 export> --target /mnt/d/padiem/chat-com2/chat.sqlite3`).
  실행하지 않는다 — 3단계에서 CTO 지시 시 수행. 복사 도구는 행 내용을 출력하지
  않고 표별 건수·해시만 남기며, 대상에 없는 표/열 불일치는 시작 전에 거부한다.

## 6. 정지·롤백

```bash
sudo systemctl stop padiem-chat-com2.service   # 병행 호스트만 멈춘다
```

공개를 닫으려면 chat-com2 전용 터널만 중지한다. 프로덕션(chat.padiem.net)에는
어떤 명령도 적용하지 않는다.

## 7. Qoder 인계 체크리스트

1. `install.sh --dry-run` 결과 확인 → `--apply`.
2. `.env` 입력(시크릿 값은 채팅·로그·PR에 남기지 않는다) → `check_config.py` 1 확인.
3. `systemctl start` 후 로컬 health PASS.
4. chat-com2 전용 터널 구성·기동 → 공개 `/health` ok.
5. 브라우저에서 가입 → 로그인 → 대화 목록 → mock 채팅 1회(모델은 mock 기본).
6. health/backup 타이머 enable, 백업 1회 수동 실행 결과 확인.
7. 보고: 설치 PASS/실패 단계, health, 터널 hostname, mock 채팅 확인 여부.

## 8. 11-01 운영 교훈

11-01 배포·로그인 운영에서 확인한 사실. 근거: PR #6558·#6559·#6561·#6563,
`docs/operations/CHAT_SPEED_20261101.md`.

### 8-1. 서비스 쓰기 가능 경로 (systemd)

- `padiem-chat-com2.service`는 `ProtectSystem=strict`라서 `ReadWritePaths`에 적힌
  두 곳만 쓸 수 있다: `/mnt/d/padiem/chat-com2`, `/opt/padiem/chat-com2/data`.
- 새 파일·새 DB는 이 두 경로 안에만 만든다. 그 밖에 두면 쓰기가 막혀
  "readonly database" 오류로 서비스가 멈추고 재시작을 반복한다(크래시 루프).

### 8-2. 앞단 검증 replay DB

- 위치: `PADIEM_COM2_EDGE_REPLAY_DB=/opt/padiem/chat-com2/data/edge-replay.sqlite3`(ext4).
- `/mnt/d`(9p)에 두면 동시 검증 때 잠금 경쟁이 생겨 정상 서명 요청도 403이 될 수
  있다(#6563). 11-01부터 검증은 한 번에 하나씩(직렬화) 처리한다.

### 8-3. deploy_from_main.sh

- 서비스 시작·롤백 확인의 health 검사는 최대 30초 재시도한다. 6~8초 기동 지연을
  실패로 오탐하지 않는다(#6558).
- B14 install.sh는 우리 유닛(Description·ExecStart 일치)이면 채택한다.
  logrotate·드롭인도 우리 파일이 있으면 채택하고, `20-log-to-file.conf`는 있을
  때만 갱신한다(#6558·#6563).
- 미러 설치에 B14와 메시 큐 코드가 포함된다. 롤백 대상에도 `padiem_ai_core`
  오버레이를 보장한다(#6563).

### 8-4. 공통 로그인

- padiem-auth는 클라이언트 설정에 `profile_claims`가 있을 때만 /token 본문에
  account_id·profile을 실는다. 새 서비스 등록 시 운영·스테이징 설정을 똑같이
  맞춘다. 11-01에는 운영 b62에만 profile_claims가 빠져 로그인이 실패했다(#6561).
- 앞단 타임아웃: `/auth/shared/callback`만 30초, 나머지 `/auth/*`는 8초(#6561).
- 11-01 운영 실측: 콜백 전체 3~3.4초, 그중 identity 1.1~1.3초.

### 8-5. 업로드 한도 (Cloudflare 무료 요금제)

- Cloudflare 무료 요금제는 요청 본문이 최대 100MB다(공식 한도).
  `chat.padiem.net`을 거치는 업로드는 100MB를 넘길 수 없다.
- 1GB 업로드를 내려면 앞단을 우회하는 구조가 필요하다. 아직 착수 전이다.

## 9. 복원 (백업 파일 → 실제 DB)

11-01부터 `padiem-chat-com2-backup.timer`가 매일 04:20에
`/mnt/d/padiem/chat-com2/backups/chat-<stamp>.sqlite3`를 남긴다. 백업이 "검증됐다"는 것과
**그 파일로 되돌아간다**는 것은 다른 문제라, 복원은 아래 순서로만 한다.
(같은 절차를 시험으로 고정: `apps/padiem-chat/tests/test_chat_com2_backup_restore.py`)

```bash
sudo systemctl stop padiem-chat-com2.service
sudo -u padiem-chat sh -c 'cd /mnt/d/padiem/chat-com2 && mv chat.sqlite3 chat.sqlite3.pre-restore-$(date -u +%Y%m%dT%H%M%SZ) && rm -f chat.sqlite3-wal chat.sqlite3-shm'
sudo -u padiem-chat cp /mnt/d/padiem/chat-com2/backups/chat-<stamp>.sqlite3 /mnt/d/padiem/chat-com2/chat.sqlite3
sudo -u padiem-chat /opt/padiem/chat-com2/venv/bin/python -c "import sqlite3;c=sqlite3.connect('/mnt/d/padiem/chat-com2/chat.sqlite3');print(c.execute('PRAGMA integrity_check').fetchone()[0],[(t,c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]) for t in ('users','conversations','messages','projects')])"
sudo systemctl start padiem-chat-com2.service
```

- 반드시 **서비스를 먼저 멈춘다.** 멈추지 않으면 되돌리는 중에 앱이 같은 파일에 쓰고,
  `-wal`이 남아 있으면 새 파일에 옛 변경이 다시 재생된다(그래서 `-wal`/`-shm`을 함께 지운다).
- 검사 기준: `integrity_check`=`ok` 이고 네 표 건수가 백업 로그의
  `CHAT_COM2_BACKUP=PASS … users=… conversations=… messages=… projects=…`와 같아야 한다.
- 마이그레이션 장부(`padiem_local_migration_ledger`)도 백업에 함께 들어 있으므로 복원 후
  이미 적용된 마이그레이션이 다시 돌지 않는다(장부 건수도 같은지 함께 본다).
- 정상 기동·로그인·대화 1건을 확인한 뒤에 `.pre-restore-<stamp>` 파일을 지운다.

### 8-6. 배포 스크립트의 두 규칙

- 대상 유닛 확인: `deploy_from_main.sh --apply`는 코드를 옮기기 전에 diff가 고른
  유닛이 모두 `enabled`인지 보고, `enabled`인데 `inactive`면 먼저 `start`한 뒤
  health 검사를 통과해야 진행한다. install.sh는 "설치 전에 켜져 있던" 유닛만
  재시작하므로, 꺼진 채로 배포하면 새 코드가 기동되지 않고 health 실패로 롤백된다
  (2026-11-01 B14 사례).
- Chat 마이그레이션 자동 적용: 대기 중인 마이그레이션이 있으면 `--apply`는 DB 옆에
  `chat.sqlite3.pre-deploy-<timestamp>` 백업을 만들고(`PRAGMA integrity_check` 확인),
  대기 파일만 `padiem_local_migration_ledger`에 기록하며 적용한 뒤 배포를 계속한다.
  `--dry-run`은 예전처럼 `MIGRATION_FIRST`로 멈춘다. 적용 주체는
  `PADIEM_COM2_CHAT_DB_USER`(기본 `padiem-chat`).
