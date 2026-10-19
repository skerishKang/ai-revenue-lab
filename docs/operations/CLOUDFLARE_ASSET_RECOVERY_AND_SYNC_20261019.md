# Cloudflare 운영 자산 동기화·복구 점검 (COM2) — 2026-10-19

COM2에서 Cloudflare 운영 자산을 어느 범위까지 복구할 수 있는지 확인한 기록과
재사용 절차입니다. 인증 경로 선택과 진단은
[CLOUDFLARE_CREDENTIAL_OPERATIONS.md](CLOUDFLARE_CREDENTIAL_OPERATIONS.md)를
따릅니다. 이 문서는 실제 Secret 값, 계정 식별자, 바인딩 전체 목록을 싣지
않습니다.

## 1. 범위

포함:

- 운영 Workers 목록, 현재 배포 버전, 배포 이력, 바인딩 이름·대상
- D1 데이터베이스 목록, 스키마 규모, Time Travel 북마크
- R2 버킷 목록과 COM2 로컬 세대 동기화 상태
- 기존 COM2 백업 구현(#5093 / PR #5096)의 복구 활용 가능성
- 위 항목을 반복 확인할 수 있는 읽기 전용 점검 도구

제외(이번 작업에서 실행하지 않음):

- 운영 D1 삭제·복원·스키마 변경
- Worker 재배포·교체·트래픽 전환
- Secret 생성·변경·조회 값 출력
- R2 객체 삭제, 원격 데이터 변경
- #5096 Worker 배포

## 2. 확인 방법

모든 Cloudflare 조회는 읽기 전용 Wrangler 명령으로 수행했습니다.

```text
wrangler deployments status --name <worker> --json
wrangler deployments list   --name <worker> --json
wrangler versions view      <version_id> --name <worker> --json
wrangler d1 list --json
wrangler d1 time-travel info <database> --json
wrangler r2 bucket list
```

반복 점검은 `scripts/ops/cloudflare_asset_snapshot.py`를 사용합니다. 이 도구는
위 명령만 호출하고, 바인딩을 이름·타입·대상으로 축약하면서 `plain_text`,
`json` 등 값 필드를 버립니다. Secret은 바인딩 이름과 저장소 참조만 남기고
값을 읽지 않습니다.

```bash
python scripts/ops/cloudflare_asset_snapshot.py capture \
    --wrangler <wrangler 실행 경로> \
    --worker <worker> [--worker <worker> ...] \
    --out <비공개 경로>/assets.json

python scripts/ops/cloudflare_asset_snapshot.py verify \
    --wrangler <wrangler 실행 경로> \
    --snapshot <비공개 경로>/assets.json
```

종료 코드:

| 코드 | 의미 |
| --- | --- |
| 0 | 캡처 성공 / 저장된 기준선과 현재 표면 일치 |
| 1 | 드리프트 발견(worker 누락·버전 변경·바인딩 변경·D1 변경·R2 추가/누락) |
| 2 | 읽기 실패, 스냅샷 파일 손상, 종류 불일치 |

스냅샷에는 버전 ID, 리소스 ID, Secret **이름**이 들어갑니다. 비공개 로컬
경로에만 보관하고 저장소·PR·이슈·로그에 첨부하지 않습니다.

## 3. 자산 위치 구분

| 자산 | Cloudflare 실행 상태 | COM2 로컬 사본 | 저장소 추적 |
| --- | --- | --- | --- |
| Worker 소스·구성 | 실행 중 | 저장소 체크아웃 | 있음(구성이 있는 Worker) |
| Worker 배포 버전·이력 | 있음 | 없음(스냅샷으로만 기록) | 없음 |
| D1 스키마·행 | 있음 | 세대별 SQLite + SQL | 없음 |
| D1 Time Travel 북마크 | 있음 | 비공개 포인터 파일 | 없음 |
| R2 객체 | 있음 | 세대별 불변 blob + 매니페스트 | 없음 |
| Secret 값 | 있음(서버 측) | DPAPI 저장소(값 미출력) | 없음 |

로컬 사본은 복구 기준선이며 운영 데이터의 정본이 아닙니다. 로컬 세대의
`production_bound` 값은 `false`입니다. Cloudflare 원격과의 동기화는 COM2
예약 작업이 수행하는 읽기 전용 수집이며, 운영 서비스가 로컬 세대를 자동으로
소비하지는 않습니다.

## 4. 확인 결과 (2026-10-19)

### Workers

- PADIEM 관련 운영 Worker 20개의 현재 버전과 바인딩 메타데이터를 읽었습니다.
  실패 0건, 모두 배포 상태로 확인했습니다.
- 일부 Worker는 저장소의 `wrangler` 구성 이름과 실제 배포 이름이 다르거나
  저장소 구성이 없습니다. 이 경우 소스 위치와 복구 방법을 별도로 확인해야
  합니다.
- 읽은 내용은 비공개 스냅샷에만 저장했고 이 문서에는 나열하지 않습니다.

### D1

- 계정 내 D1 5개를 확인했습니다. 복제 기준 대상은 채팅·엔진 2개이고 나머지는
  QA·보조 데이터베이스입니다.
- 두 기준 데이터베이스를 읽기 전용 원격 export로 새 로컬 세대로 캡처했고,
  각 SQLite에 `PRAGMA integrity_check=ok`를 확인했습니다. 채팅 57개,
  엔진 10개 테이블입니다.
- 5개 데이터베이스 모두 Time Travel 북마크를 읽었습니다. 북마크 값은 비공개
  포인터 파일에만 기록했습니다.
- 이전 로컬 세대와 비교해 채팅 데이터베이스에 애플리케이션 테이블 6개와 행
  증가가 있었고, 이번 캡처로 로컬 세대를 현재 상태에 맞췄습니다.

### D1 복원 검증

- `scripts/ops/d1_restore_verify.py`로 원격 export SQL을 임시 SQLite에
  복원하고 원본 세대 SQLite와 비교했습니다. 복원 대상은 임시 작업
  디렉터리뿐이고, 운영 D1과 기존 세대 파일은 읽기 전용으로 열었습니다.
- 검증 세대: `20261019T005025448605Z`, `20261019T084623611470Z`,
  `20261019T084722757869Z`. 세 세대 모두 아래 항목을 통과했습니다.
  - 채팅: 애플리케이션 테이블 56개(SQLite 내부 테이블 포함 57개), 행 1,018개
  - 엔진: 테이블 10개, 행 85개
  - 스키마 일치(누락·추가·정의 변경 0), 테이블별 행 수 일치
  - `PRAGMA integrity_check=ok`, `PRAGMA foreign_key_check` 위반 0
  - 원본 SQLite SHA-256이 복원 전후 동일(도구가 원본을 수정하지 않음)
- 새 원격 export 두 건은 이전 캡처와 바이트 단위로 같았습니다. 확인 시점의
  채팅·엔진 D1은 로컬 세대와 내용 차이가 없었습니다.
- 도구는 종료 코드 0(일치)·1(불일치)·2(입력 사용 불가)를 사용합니다.
  리포트에는 테이블 이름, 행 수, 해시, 무결성 결과만 기록하고 행 내용은
  남기지 않습니다.

```bash
python scripts/ops/d1_restore_verify.py \
    --sql <세대>/chat.sql --reference <세대>/chat.sqlite3
python scripts/ops/d1_restore_verify.py \
    --sql <세대>/engine.sql --reference <세대>/engine.sqlite3
```

### R2

- 계정 내 버킷 4개를 확인했습니다. 동기화 대상 3개(workspace·b66 QA·media)의
  원격 열거는 각 1페이지, `truncated=false`였습니다.
- 기존 게시 세대 대비 workspace 신규 객체 6개, 변경 0, 원격 삭제 0이었습니다.
  기존 증분 동기화 절차로 6개를 복사하고 새 세대를 게시했습니다.
- 새 세대는 148개 객체 전체의 크기·ETag·SHA-256 검증을 통과했습니다
  (workspace 40 / QA 3 / media 105).
- 정기 동기화 점검 시점의 원격 열거도 40 / 3 / 105개였고, 기준 세대 대비
  신규·변경·원격 삭제가 모두 0이었습니다. 이 경우 증분 복사를 실행하지
  않고 기존 세대를 유지합니다.

### Secret

- 이름과 바인딩 종류만 확인했고 값은 읽거나 출력하지 않았습니다.
- COM2 DPAPI 저장소와 Cloudflare 서버 측 Secret은 서로 다른 저장 위치입니다.
  Cloudflare에서 값을 export하는 복구 경로는 사용하지 않았습니다.

### #5096 COM2 백업 구현

- `apps/com2-backup`과 `scripts/ops/com2_backup.py` 소스는 병합되어 있습니다.
- Worker는 배포되지 않았고 `COM2_BACKUP_ENABLED` 게이트는 꺼져 있으며 Secret도
  생성되지 않았습니다. 현재 상태로는 라이브 복구 경로가 아닙니다.
- 이 구현은 COM2 로컬 파일의 전송·검증·빈 대상 복원 점검용입니다. D1·R2
  운영 데이터를 대신 백업하지 않습니다. 페이로드 상한 32 MiB, 덮어쓰기 없음,
  삭제 없음, `restore-check`는 빈 대상에만 기록합니다.
- 사용하려면 승인된 배포, 게이트·Secret 구성, 실제 환경 왕복 검증이 순서대로
  필요합니다.

## 5. 자산별 복구 가능 범위

### Workers

가능:

- 저장소 구성이 있는 Worker는 소스와 `wrangler` 구성으로 재배포 경로를
  재구성할 수 있습니다.
- Cloudflare의 배포 이력에서 이전 버전 ID를 확인해 롤백 대상을 특정할 수
  있습니다.
- 현재 버전·바인딩 이름·대상은 스냅샷과 대조할 수 있습니다.

제한:

- 저장소 구성이 없는 Worker는 배포된 코드를 별도로 확보하기 전까지 소스
  복구가 보장되지 않습니다.
- Secret 값은 조회로 복구할 수 없습니다. 승인된 재발급·재설정이 필요합니다.

### D1

가능:

- Time Travel 북마크로 Cloudflare 보존 기간 내 복원 지점을 특정할 수 있습니다.
- 로컬 SQLite 세대와 SQL export를 별도 데이터베이스에 적재해 복구 리허설을
  할 수 있습니다.
- 이전 마이그레이션 전 사전 백업 SQL이 COM2에 보존되어 있습니다.

제한:

- Time Travel 실제 복원은 실행하지 않았습니다. 보존 기간이 지나면 해당
  북마크는 사용할 수 없습니다.
- 두 데이터베이스의 로컬 세대는 동시점 트랜잭션이 아닙니다.

### R2

가능:

- 게시된 로컬 세대의 불변 blob과 매니페스트로 객체 무결성을 재검증할 수
  있습니다.
- 원격 열거와 세대를 비교해 신규·변경·원격 삭제를 구분할 수 있습니다.

제한:

- 로컬 세대를 Cloudflare로 되돌리는 업로드는 실행하지 않았습니다.
- 원격에서 삭제된 객체는 로컬에서도 삭제하지 않습니다. 삭제 전파 정책은
  정해지지 않았습니다.

### Secret

- 복구는 값 복원이 아니라 승인된 재발급으로 수행합니다.
- 어떤 Secret이 어떤 Worker에 필요한지는 스냅샷의 이름·타입으로 확인할 수
  있습니다. 값과 발급 절차는 비공개 운영 저장소의 승인 범위를 따릅니다.

## 6. 정기 동기화 운영 (COM2)

`scripts/ops/com2_periodic_sync.py`는 기존 `refresh_d1.py`와 `r2_sync.py`를
순서대로 호출하는 실행기입니다. 새 복사·검증 로직을 만들지 않고 기존 절차가
게시하는 세대, 매니페스트, SHA-256을 그대로 사용합니다.

순서:

1. D1 새 세대 생성(`refresh_d1.py`: 읽기 전용 원격 export → SQLite →
   integrity 확인 → 원자적 게시)
2. R2 원격 열거(`inventory.mjs` 로컬 Worker, 3개 버킷)
3. 열거 완전성 확인(`truncated=false`, 선언 개수와 실제 객체 수 일치)
4. 기준 세대와 diff
5. 신규·변경 객체가 있을 때만 전체 증분 동기화(`r2_sync.py`)

안전 동작:

- 단일 인스턴스 잠금(`scheduled-sync.lock`)으로 실행이 겹치지 않습니다.
  비정상 종료로 남은 잠금은 기준 시간이 지난 경우에만 교체합니다.
- 실행 종료 시 `scheduled-sync-status.json`을 원자적으로 갱신합니다. 상태에는
  단계, 종료 코드, 세대 ID, 객체 개수만 기록합니다.
- D1 단계가 실패하면 R2 단계를 시작하지 않습니다.
- R2 변경이 없으면 복사·게시를 생략하고 `R2_UNCHANGED`로 끝냅니다. 같은
  상태에서 재실행해도 객체를 중복 복사하지 않습니다.
- 열거·요청 실패는 최대 3회 재시도합니다. 재시도 후에도 실패하거나 열거가
  불완전하면 diff·복사 전에 실행을 실패로 기록합니다.
- 원격 R2 객체를 삭제·덮어쓰지 않습니다. 원격에서 사라진 객체는 diff 개수로만
  기록합니다.

예약 작업:

```text
이름: PADIEM-COM2-D1-R2-Sync
주기: 매일 04:20
사용자: 현재 COM2 로그온 사용자(대화형, 제한 권한)
동작: powershell.exe -NoProfile -ExecutionPolicy Bypass -File <COM2>/run-scheduled-sync.ps1
```

- DPAPI Secret 저장소는 같은 사용자 컨텍스트에서만 복호화되므로 실행 사용자를
  바꾸지 않습니다.
- 기존 `PADIEM-*` 예약 작업과 04시대 실행이 겹치지 않는 시각으로 등록했습니다.
- 등록 후 한 번 실제 실행해 `LastTaskResult=0`, 새 D1 세대 게시, R2 변경 없음,
  잠금 해제를 확인했습니다.

```bash
python scripts/ops/com2_periodic_sync.py install-task \
    --root <COM2 storage-migration 경로> --repo <저장소 체크아웃>
python scripts/ops/com2_periodic_sync.py run \
    --root <COM2 storage-migration 경로> --wrangler <wrangler 실행 경로>
python scripts/ops/com2_periodic_sync.py status \
    --root <COM2 storage-migration 경로>
python scripts/ops/com2_periodic_sync.py remove-task
```

집중 검증은 `scripts/ops/tests/test_d1_restore_verify.py` 8건,
`scripts/ops/tests/test_com2_periodic_sync.py` 14건입니다. 실패 단계 기록,
재시도, 부분 열거 차단, 잠금, 중복 실행, 상태 파일 비밀값 미기록을 스텁
스크립트와 스텁 HTTP 서버로 확인합니다.

## 7. 남은 격차와 담당 범위

| 격차 | 현재 상태 | 다음 동작 | 담당 범위 |
| --- | --- | --- | --- |
| #5096 Worker 미배포 | 소스만 병합, 게이트 OFF | 배포 승인 → Secret 구성 → 실제 왕복 점검 | Owner 승인 후 CTO |
| D1 원격 복원(Time Travel) | 로컬 복원 검증 완료, 원격 복원 미실행 | 보존 기간·복원 지점 결정 후 승인된 리허설 | Owner 승인 필요 |
| 저장소 구성 없는 Worker | 배포 코드 미확보 | 버전 코드 확보 또는 정리 결정 | CTO |
| Secret 재발급 절차 | 이름만 확인 | 비공개 승인 범위에서 재발급 절차 확정 | Owner·비공개 거버넌스 |
| R2 원격 삭제 정책 | 차이만 기록 | 보존·삭제 정책 결정 | Owner |
| 예약 실행 감시 | 상태 파일·로그만 로컬 기록 | 실패 알림 필요 여부 결정 | 운영 |

## 8. 이번 작업에서 하지 않은 것

- 운영 D1 복원, Worker 교체, Secret 변경, 트래픽 전환
- #5096 Worker 배포
- R2 원격 업로드·삭제
- Secret 값 조회·출력
- 기존 예약 작업의 일정 변경·중지(신규 작업만 등록)
