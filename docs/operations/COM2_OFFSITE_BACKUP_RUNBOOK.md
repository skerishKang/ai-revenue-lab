# COM2 오프사이트 암호화 백업 런북 (R2, #5093)

```text
DOC_ROLE=COM2_OFFSITE_BACKUP_RUNBOOK
STATUS=스크립트·유닛·리허설 준비 완료 / 설치·자격·첫 실행은 Qoder (배포 없음)
RELATED=deploy/host-com2/offsite-backup/, docs/operations/CHAT_COM2_RUNBOOK.md
경계: R2 버킷·토큰 생성과 컴2 설치는 이 문서의 인계 절차로만 한다.
```

## 1. 무엇을 어디에

- 원본: 각 서비스의 일 백업(이미 `VACUUM INTO` + 자체 검증) — 큐 `/opt/padiem/backups/mesh-queue`, Chat `/mnt/d/padiem/chat-com2/backups`, broker `/mnt/d/padiem/broker/backups`.
- R2 객체: `offsite/v1/{service}/daily/{YYYYMMDD}.cbe1` + `.json`(manifest), 주간 사본 `offsite/v1/{service}/weekly/{YYYY-Www}.cbe1` + `.json`.
- 암호문만 올라간다: `scripts/ops/com2_backup.py`의 **PADIEM-CBE1** 봉투(AES-256-GCM, AAD=서비스+백업 id)를 그대로 재사용. 키 파일은 컴2에만(0600), **R2·백업·로그·PR 어디에도 없다**. broker pepper는 애초에 백업 대상이 아니다(설계 §4 결정).
- 업로드 직후 payload·manifest를 **다시 내려받아** SHA-256 대조. 불일치면 실행 실패(종료 3).

## 2. 보관·비용

- 기본: 일 7개 + 주 4개(서비스당 최대 11세대) — `OFFSITE_RETENTION_DAILY/WEEKLY`로 조정.
- R2 무료 한도(Cloudflare 공식): 저장 10 GB-month, Class A 1,000,000회/월, Class B 10,000,000회/월, egress 무료. 새 Cloudflare cron은 쓰지 않는다(systemd timer).
- 계산(2026-10-29 기준 공식 한도, 실측 크기는 Qoder가 `du`로 대체):
  | 서비스 | 예시 크기(암호문≈원본) | 보관 11세대 |
  |---|---|---|
  | chat | 50 MB | 550 MB |
  | queue | 10 MB | 110 MB |
  | broker | 2 MB | 22 MB |
  | 합계 | 62 MB | **682 MB** ≪ 10 GB |
  - 10배 커져도(620 MB/일) 6.8 GB로 한도 내. **1GB/서비스**를 넘기면 한도 초과 → 보관 세대 조정 결정(이 도구는 정책을 임의 확정하지 않는다).
- 요청: 서비스당 실행 1회 = PUT 2 + GET 2(검증) + LIST 1 + DELETE ≤2 ≈ Class A 5 / Class B 3. 일 3서비스 → 월 ≈ **Class A 465 / Class B 280** — 한도(1M/10M)의 0.1% 미만. 일요일 주간 사본 +2 PUT/GET.

## 3. Qoder 인계 목록

1. **R2 버킷**: 전용 버킷(가칭 `padiem-com2-offsite`). 기존 `padiem-workspace-files`와 분리 보관 권장(수명주기·권한 분리).
2. **토큰(최소 권한)**: Object Read & Write, **이 버킷만**. 필요한 동작: PutObject, GetObject, ListObjects(ListBucket), DeleteObject. 계정 전역 권한·버킷 생성 권한은 불필요. 발급한 Access Key ID/Secret을 0600 파일 두 개(`/etc/padiem/r2-offsite-token-id`, `-secret`)로 저장, 값은 대화·로그·PR에 남기지 않는다.
3. **키 파일**: `umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > /etc/padiem/offsite-backup.key; chmod 600` — 화면에 출력하지 않는다(리다이렉트만). `COM2_OFFSITE_KEY_ID`(비밀 아님, 예 `com2-2026-11`)를 env에 기록. **키 분실 = 복구 불가**이므로 키 파일은 별도 오프라인 보관(예: 비밀 금고). R2에 절대 올리지 않는다.
4. **설치**: `bash deploy/host-com2/offsite-backup/install.sh --dry-run` → `--apply`(키 파일·env 선존재 검사, 시작·enable 없음).
5. **env**: `/etc/padiem/offsite-backup.env`(0600) — endpoint·버킷·토큰 파일 경로·백업 디렉터리·보관 수. 예시 파일 참조.
6. **첫 실행(수동)**: `systemctl start padiem-offsite-backup.service` → `journalctl -u …`에 `OFFSITE_UPLOAD=PASS service=… sha256=…` 3줄 확인. 이어서 `offsite.py list --service chat`로 객체 확인.
7. **타이머**: `systemctl enable --now padiem-offsite-backup.timer`(05:10 UTC, Persistent).

## 4. 복구 절차

1. 서비스 **정지**: 예 `systemctl stop padiem-chat-com2.service` (broker/queue 동일). 라이브 파일을 열어둔 채 덮어쓰지 않는다.
2. 대상 확인: `offsite.py list --service chat` (날짜/크기만). 주간 세대는 `2026-W44` 표기.
3. 복구(스크립트가 해시 검증 → 복호화 → integrity_check → 교체):
   ```bash
   /opt/padiem/offsite-backup/venv/bin/python /opt/padiem/offsite-backup/offsite.py restore \
     --service chat --date 20261102 --target /mnt/d/padiem/chat-com2/chat.sqlite3 --replace
   ```
   `OFFSITE_RESTORE=PASS … tables=N replaced=True`가 아니면 중단. 기존 파일은 `<name>.pre-restore-<ts>`로 옆에 보존된다.
4. 기동: `systemctl start padiem-chat-com2.service` → 로컬 `/health` PASS → 대표 시나리오(로그인·목록·mock 채팅 1회).
5. 행 수 확인: 정지 전 기록한 표별 건수와 대조(백업 로그 `MESH_QUEUE_BACKUP=OK rows=…`, `CHAT_COM2_BACKUP=PASS …`, `BROKER_BACKUP=PASS …`).

## 5. 한계·주의

- 키 파일을 잃으면 어떤 백업도 복호화할 수 없다. 키는 DB 백업과 **분리** 보관한다.
- 같은 날 재실행은 같은 객체 키를 덮어쓴다(암호문은 새 nonce). 하루 1회 운영을 전제한다.
- 업로드는 백업 존재·신선도(26시간 내)를 검사한다. 오래된 파일이면 `backup_stale`로 실패 — 백업 레인 자체가 멈췄다는 신호다.
- R2 버킷·토큰·키 생성은 이 저장소 PR로 자동화하지 않는다(비밀 취급).
