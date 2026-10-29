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

- 처음엔 빈 SQLite + 마이그레이션 001~078 자동 적용(부팅 시, 자체 장부; 최종 번호는 현재 main의 migrations 최신 파일 기준).
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

## 8. 마이그레이션 장부 점검

`python tools/check_chat_migration_ledger.py --db <SQLite 사본> --ledger d1_migrations`로
현재 체크아웃의 모든 마이그레이션 파일과 장부를 읽기 전용 비교한다. 컴2 로컬 장부는
`--ledger padiem_local_migration_ledger`를 사용한다. MISMATCH 또는 ERROR는 전환 중단이다.
076 백업을 078 대상에 직접 복사하면 project_files 열 불일치로 거부된다.
