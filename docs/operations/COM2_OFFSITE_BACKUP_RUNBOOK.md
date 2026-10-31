# COM2 오프사이트 암호화 백업 런북 (R2, #5093)

```text
DOC_ROLE=COM2_OFFSITE_BACKUP_RUNBOOK
STATUS=스크립트·유닛·리허설 준비 완료 / 설치·자격·첫 실행은 Qoder (배포 없음)
RELATED=deploy/host-com2/offsite-backup/, docs/operations/CHAT_COM2_RUNBOOK.md,
        docs/operations/COM2_UNATTENDED_BACKUP_OPERATIONS_20261019.md
경계: R2 버킷·토큰 생성과 컴2 설치는 이 문서의 인계 절차로만 한다.
```

## 1. 무엇을 어디에

- 원본(서비스 스냅샷): 각 서비스의 일 백업(이미 `VACUUM INTO` + 자체 검증) — 큐 `/opt/padiem/backups/mesh-queue`, Chat `/mnt/d/padiem/chat-com2/backups`, broker `/mnt/d/padiem/broker/backups`.
- 원본(D1 세대): 매일 04:20 Windows 작업 `PADIEM-COM2-D1-R2-Sync`가 게시하는
  `D:\PADIEM-Servers\infrastructure\storage-migration\snapshots\generations\<id>\{chat,engine}.sqlite3`
  (WSL에서 `/mnt/d/PADIEM-Servers/...`). **컴2 디스크 한 곳에만 있는 진짜 데이터**이므로
  `d1-chat`·`d1-engine` 두 대상으로 오프사이트에 넣는다.
  - 어느 세대가 원본인지는 이 도구가 직접 판단하지 않는다: 검증된 권한
    `scripts/ops/com2_backup_schedule.py::resolve_generation`이 포인터
    `snapshots/current_generation.json`을 읽고 세대별 seed를 **다시 해싱**해 맞아야만 넘긴다.
    즉 반쯤 게시된 세대·`.pending` 디렉터리·바이트가 어긋난 seed는 백업 대상이 되지 못한다.
  - 원본은 **읽기만** 한다. 유닛이 `/mnt/d/PADIEM-Servers`를 `ReadOnlyPaths`에 넣어 커널 수준에서
    쓰기를 막는다.
  - 신선도는 세대 id(`%Y%m%dT%H%M%S%fZ`)를 capture 기준으로 판정한다. 26시간 초과 → `FAIL`.
- R2 객체: `offsite/v1/{service}/daily/{YYYYMMDD}.cbe1` + `.json`(manifest), 주간 사본 `offsite/v1/{service}/weekly/{YYYY-Www}.cbe1` + `.json`.
- 암호문만 올라간다: `scripts/ops/com2_backup.py`의 **PADIEM-CBE1** 봉투(AES-256-GCM, AAD=서비스+백업 id)를 그대로 재사용. 키 파일은 컴2에만(0600), **R2·백업·로그·PR 어디에도 없다**. broker pepper는 애초에 백업 대상이 아니다(설계 §4 결정).
- 업로드 직후 payload·manifest를 **다시 내려받아** SHA-256 대조. 불일치면 실행 실패(종료 3).

## 2. 서비스별 상태 (하나라도 없으면 전체가 멈추던 문제의 해결)

매 실행은 대상마다 한 줄을 내고, 마지막에 종합 판정을 낸다.

```text
OFFSITE_SERVICE=<name> STATUS=<OK|FAIL|NOT_INSTALLED|UNKNOWN> [REASON=...] [BACKUP=... SOURCE=... GENERATION=... BYTES=... SHA256=...]
OFFSITE_RUN=<PASS|FAIL|UNKNOWN> UPLOADED=<n> FAILED=<names|->
```

| 상태 | 뜻 | 판정에 영향 |
|---|---|---|
| `OK` | 원본을 찾아 암호문 업로드·재검증까지 끝 | 성공 |
| `NOT_INSTALLED` | 이 호스트에 그 서비스가 없다 — 유닛 파일도 없고 원본 경로도 없다 | **실패 아님**, 보고만 한다 |
| `FAIL` | 설치됐는데 백업이 없거나(`backup_missing:*`), 26시간보다 오래됐거나(`backup_stale`, `generation_stale:*h`), 세대가 검증 통과 못함(`generation:*_integrity_failed`) | 하나라도 있으면 **전체 실패(종료 3)** |
| `UNKNOWN` | 판단 근거가 없음 — 예: 세대 id가 시각이 아니라 신선도를 계산할 수 없다, 또는 이번 실행이 아무것도 올리지 못했다 | 성공이 아니다 |

- 분류는 업로드보다 먼저 끝난다. 그래서 큐가 `FAIL`이어도 Chat·broker·D1 두 세대는 자기 사본을
  밖으로 보낸다(2026-10-29 첫 실행이 `backup_missing:mesh-queue` 하나로 전부 멈췄던 반例).
- D1은 한 세대를 두 라벨이 함께 쓴다. 따라서 `chat.sqlite3` 바이트가 manifest와 다르면
  `d1-chat`만 아니라 `d1-engine`도 `FAIL`이다 — 서로 다른 순간의 두 파일을 버킷에 놓지 않는다.
- 큐를 방금 설치한 상태가 정상적으로 `FAIL`이다(서비스는 있는데 첫 스냅샷이 아직 없음). 그 첫
  세대까지 백업 타이머가 돌아야 `OK`로 바뀐다.

## 3. 보관·비용

- 기본: 서비스당 일 7개 + 주 4개(최대 11세대) — `OFFSITE_RETENTION_DAILY/WEEKLY`로 조정.
- R2 무료 한도(Cloudflare 공식): 저장 10 GB-month, Class A 1,000,000회/월, Class B 10,000,000회/월, egress 무료. 새 Cloudflare cron은 쓰지 않는다(systemd timer).
- 계산(2026-10-29 기준. D1 크기는 `refresh_d1.py`에 기록된 실측 — chat export 1.48 MB — 과 리허설로 측정한 봉투 오버헤드(+53 B) 사용. 스냅샷 크기는 Qoder가 `du`로 대체):
  | 대상 | 예시 크기(암호문≈원본) | 보관 11세대 |
  |---|---|---|
  | chat | 50 MB | 550 MB |
  | queue | 10 MB | 110 MB |
  | broker | 2 MB | 22 MB |
  | d1-chat | 1.5 MB | 16.5 MB |
  | d1-engine | 0.3 MB | 3.3 MB |
  | 합계 | 63.8 MB | **≈702 MB** ≪ 10 GB |
  - 10배 커져도(638 MB/일) 7 GB로 한도 내. **1GB/대상**을 넘기면 한도 초과 → 보관 세대 조정 결정(이 도구는 정책을 임의 확정하지 않는다).
- 요청: 대상당 실행 1회 = PUT 2 + GET 2(검증) + LIST 1 + DELETE ≤2 ≈ Class A 5 / Class B 3. 일 5대상 → 월 ≈ **Class A 775 / Class B 465** — 한도(1M/10M)의 0.1% 미만. 일요일 주간 사본 +2 PUT/GET.

## 4. Qoder 인계 목록

1. **R2 버킷**: 전용 버킷(가칭 `padiem-com2-offsite`). 기존 `padiem-workspace-files`와 분리 보관 권장(수명주기·권한 분리).
2. **토큰(최소 권한)**: Object Read & Write, **이 버킷만**. 필요한 동작: PutObject, GetObject, ListObjects(ListBucket), DeleteObject. 계정 전역 권한·버킷 생성 권한은 불필요. 발급한 Access Key ID/Secret을 0600 파일 두 개(`/etc/padiem/r2-offsite-token-id`, `-secret`)로 저장, 값은 대화·로그·PR에 남기지 않는다.
3. **키 파일**: `umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > /etc/padiem/offsite-backup.key; chmod 600` — 화면에 출력하지 않는다(리다이렉트만). `COM2_OFFSITE_KEY_ID`(비밀 아님, 예 `com2-2026-11`)를 env에 기록. **키 분실 = 복구 불가**이므로 키 파일은 별도 오프라인 보관(예: 비밀 금고). R2에 절대 올리지 않는다.
4. **설치**: `bash deploy/host-com2/offsite-backup/install.sh --dry-run` → `--apply`.
   - 이제 이 설치는 `scripts/ops/com2_backup.py`(봉투)와 `scripts/ops/com2_backup_schedule.py`(세대 권한)를
     `$app`에 심볼릭 링크로 두고, 둘의 import를 설치 단계에서 확인한다(실패 시 `CRYPTO_IMPORT_FAILED`,
     `GENERATION_IMPORT_FAILED`). 저장소 체크아웃이 그 자리에 있어야 하므로 `--source-root`를 확인한다.
   - 시작·enable는 여전히 하지 않는다. 예약 작업(`PADIEM-COM2-D1-R2-Sync`)은 이 문서의 대상이 아니다.
5. **env**: `/etc/padiem/offsite-backup.env`(0600) — endpoint·버킷·토큰 파일 경로·백업 디렉터리·
   `OFFSITE_D1_GENERATIONS_DIR`·`OFFSITE_D1_RUNTIME_POINTER`(비워 두면 게시 포인터만 사용)·보관 수.
   예시 파일 참조. 값은 경로·이름·숫자만, 비밀은 파일 경로로만 들어온다.
6. **리허설(로컬 더블로 먼저)** — 실제 버킷을 건드리지 않고 왕복을 증명한다:
   ```bash
   OFFSITE_R2_DIR=/tmp/offsite-rehearse OFFSITE_STATE_DIR=/tmp/offsite-rehearse/state \
     /opt/padiem/offsite-backup/venv/bin/python /opt/padiem/offsite-backup/offsite.py \
     rehearse --service d1-chat
   ```
   `OFFSITE_REHEARSAL=PASS service=d1-chat … tables=N rows=M integrity=ok sha256=…` 확인.
   `rehearse`는 `OFFSITE_R2_DIR`이 없으면 `rehearse_requires_local_bucket`로 거부한다(프로덕션
   버킷에 리허설 객체를 남길 수 없다).
7. **첫 실 실행(수동)**: `systemctl start padiem-offsite-backup.service` → `journalctl -u …`에서
   대상별 `OFFSITE_SERVICE=… STATUS=…` 5줄과 `OFFSITE_RUN=PASS`를 확인한다. `NOT_INSTALLED`는
   보고일 뿐이고, `FAIL`이 보이면 그 대상만 고친 뒤 재실행한다(종료 코드는 FAIL/UNKNOWN일 때 3).
   이어서 `offsite.py list --service d1-chat`으로 객체 확인.
8. **타이머**: `systemctl enable --now padiem-offsite-backup.timer`(05:10 UTC, Persistent).

## 5. 복구 절차

1. 서비스 **정지**: 예 `systemctl stop padiem-chat-com2.service` (broker/queue 동일). 라이브 파일을 열어둔 채 덮어쓰지 않는다.
2. 대상 확인: `offsite.py list --service chat` (날짜/크기만). 주간 세대는 `2026-W44` 표기.
3. 복구(스크립트가 해시 검증 → 복호화 → integrity_check → 교체):
   ```bash
   /opt/padiem/offsite-backup/venv/bin/python /opt/padiem/offsite-backup/offsite.py restore \
     --service chat --date 20261102 --target /mnt/d/padiem/chat-com2/chat.sqlite3 --replace
   ```
   `OFFSITE_RESTORE=PASS … tables=N rows=M replaced=True`가 아니면 중단. 기존 파일은 `<name>.pre-restore-<ts>`로 옆에 보존된다.
   `--replace` 없이 실행하면 검증만 하고 staging 파일(`state/restore/...`)을 남긴다 — D1 세대는
   이렇게 **별도 파일로** 꺼내는 것이 기본이다(아래 5).
4. 기동: `systemctl start padiem-chat-com2.service` → 로컬 `/health` PASS → 대표 시나리오(로그인·목록·mock 채팅 1회).
5. 행 수 확인: 정지 전 기록한 표별 건수와 대조(백업 로그 `MESH_QUEUE_BACKUP=OK rows=…`, `CHAT_COM2_BACKUP=PASS …`, `BROKER_BACKUP=PASS …`).
   - D1 세대를 다시 열어 확인할 때는 표 이름까지 대조한다: `restore`가 낸 staging 파일을
     `python3 -c 'import sys; sys.path.insert(0,"/opt/padiem/offsite-backup"); import offsite; print(offsite.table_row_counts(__import__("pathlib").Path(sys.argv[1])))' <staged>`
     또는 같은 함수로 원본 세대 seed와 비교한다. `rehearse`가 이미 이 비교를 한다(§4-6).
   - D1 복구로 **라이브 세대를 덮지 않는다**: 다음 04:20 작업이 새 세대를 게시하고 포인터를
     옮기므로, 필요하면 별도 경로에 꺼내 비교한 뒤 판단한다. 세대 디렉터리·포인터 쓰기는
     이 도구의 범위가 아니고 유닛이 읽기로만 마운트한다.

## 6. 한계·주의

- 키 파일을 잃으면 어떤 백업도 복호화할 수 없다. 키는 DB 백업과 **분리** 보관한다.
- 같은 날 재실행은 같은 객체 키를 덮어쓴다(암호문은 새 nonce). 하루 1회 운영을 전제한다.
- 업로드 대상이 `FAIL`이면 그 대상의 사본은 올라가지 않는다. 스냅샷·세대가 없다는 뜻이니
  백업 레인 자체(또는 04:20 작업)가 멈춘 것은 아닌지 본다 — `UNKNOWN`은 성공이 아니다.
- D1 세대의 신선도는 포인터가 가리키는 세대 id(시각) 기준이다. 04:20 작업이 멈춰 최신 세대가
  26시간을 넘으면 `generation_stale:<n>h`로 `FAIL`되고, 이전 세대는 백업하지 않는다(낡은 것을
  지켜진 것처럼 보이는 것을 막는다).
- D1 두 라벨은 한 세대를 공유한다. 한 라벨의 seed가 manifest 해시와 안 맞으면 두 라벨 모두
  `FAIL`이다(서로 다른 순간의 짝을 버킷에 남기지 않는다).
- `OFFSITE_D1_RUNTIME_POINTER`를 설정하면 B62 런타임 포인터와도 대조한다(런타임이 낡은 세대를
  보는 중이면 기록하고, 존재하지 않는 세대를 가리키면 `FAIL`). 기본은 미설정 = 게시 포인터만.
- 원본이 있는 드라이브는 `OFFSITE_D1_MOUNT_ROOT`(기본 `/mnt/d`)로 판정한다. 마운트가 없으면
  `NOT_INSTALLED`(보고만), 마운트됐는데 게시된 세대가 없으면 `FAIL`
  (`generation:generation_manifest_missing`) — 04:20 작업이 멈춘 것을 `NOT_INSTALLED`로 숨기지 않는다.
- R2 버킷·토큰·키 생성은 이 저장소 PR로 자동화하지 않는다(비밀 취급).

## 7. 컴1 복원 훈련 절차 (운영 교체 없음)

이 절은 세 대상의 백업을 컴1의 격리된 staging에 복원하고 검증하는 훈련이다. R2 쓰기·삭제, 운영 D1 쓰기, 서비스 설정 변경 및 `--replace` 사용은 금지한다. 복원 파일과 키는 저장소 밖에 보관하고 삭제하지 않는다.

1. 독립된 최신 main 작업 디렉터리와 저장소 밖 복원 디렉터리를 준비한다. 승인된 R2 읽기 전용 인증과 복호화 키 파일의 접근 권한을 확인한다. 키와 토큰 값은 화면·로그·명령행 인자에 넣지 않는다.
2. 대상 `d1-chat`, `d1-engine`, `queue` 각각에서 최신 daily 세대의 매니페스트와 암호문을 같은 날짜로 내려받는다. 날짜는 UTC 기준이다. R2 키는 `offsite/v1/{service}/daily/{YYYYMMDD}.json` 및 `{YYYYMMDD}.cbe1`이다. 승인된 읽기 전용 목록 조회나 UTC 날짜 역순 조회를 사용하고 검색 범위를 기록한다. 다운로드 명령의 성공 종료와 두 파일의 크기가 0보다 큰지 확인한 후 매니페스트를 파싱해 서비스와 날짜가 일치하는지 확인한다. 실패한 다운로드가 빈 파일을 남길 수 있으므로 파일 존재만으로 성공을 판정하지 않는다.
3. 내려받은 파일을 복원 폴더 아래 위의 객체 키와 같은 상대 경로에 둔다. 현재 프로세스 환경에 `OFFSITE_R2_DIR`을 다운로드 루트로, `OFFSITE_STATE_DIR`을 별도 상태 디렉터리로, `OFFSITE_CRYPTO_PATH`를 저장소의 `scripts/ops/com2_backup.py` 경로로 설정한다. `COM2_OFFSITE_KEY_FILE`은 보호된 키 파일 경로, `COM2_OFFSITE_KEY_ID`는 매니페스트에 맞는 키 ID로 설정한다. 이 설정에는 키 값 자체를 넣지 않는다.
4. 각 대상에 대해 다음 명령을 실행한다. 경로와 날짜는 훈련 환경에 맞게 대체하고 운영 대상 경로를 지정하지 않는다.

   ```powershell
   python "<repo>\deploy\host-com2\offsite-backup\offsite.py" restore --service <service> --date <UTC-YYYYMMDD>
   ```

   종료 코드와 결과의 `replaced=False`를 확인한다. 도구는 암호문 해시와 키 ID를 확인하고 AES-GCM 인증·복호화, 평문 해시 및 SQLite `integrity_check`를 수행한다. 어느 단계든 실패하면 중단하고 원인을 기록한다.
5. staging SQLite를 Python `sqlite3` 읽기 전용 모드로 열고 `PRAGMA query_only=ON`을 적용한다. `sqlite_master`의 테이블 스키마, 테이블별 `COUNT(*)`, `PRAGMA integrity_check`를 기록한다. 데이터 행과 키는 보고서에 넣지 않는다.
6. 승인된 운영 D1 읽기 전용 경로에서 동일한 스키마와 테이블별 행 수를 조회하고 비교한다. 조회 시각, 매니페스트 생성 시각과 원본 스냅샷 시각을 각각 기록해 시간 차이로 인한 변동 가능성을 표시한다. 큰 결합 쿼리가 거절되면 작은 묶음으로 나눈다. 접근이 거절되는 내부 테이블은 미조회로 기록하며 우회하지 않는다. 예를 들어 `_cf_KV`가 운영 메타데이터에만 보이면 백업에 없고 행 수는 확인할 수 없음을 기록하고 복구 필요성은 별도 판정한다. queue는 DB 재구축 시각과 백업 시각의 선후도 기록한다.
7. 탐색 시작부터 다운로드·복호화·검증 완료까지의 시간과 각 단계의 실패·재시도를 기록한다. staging 검증 시간은 서비스 교체와 재기동을 포함한 전체 RTO가 아니다. 결과에는 대상별 성공 여부, 해시·무결성, 스키마·행 수 차이, 누락 테이블, 제한과 개선점을 적는다. 복원 파일, 매니페스트, 키 및 상세 인벤토리는 저장소에 커밋하지 않는다.
