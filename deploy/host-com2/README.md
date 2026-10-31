# COM2 호스트 배포 자산

`deploy/host-com2/`는 컴2(Linux/WSL)에서 돌아가는 각 서비스의 설치 스크립트, systemd 유닛 템플릿,
설정 게이트와 검사 도구를 담는다. 이 저장소의 어떤 스크립트도 Cloudflare·터널·Windows `18731`
릴리스에 손대지 않는다. 서브디렉터리마다 사용법이 다르므로 각 `install.sh`와 `README`를 먼저 읽는다.

| 디렉터리 | 역할 |
| --- | --- |
| `chat/` | Chat 본체(127.0.0.1:8798), 헬스·백업 타이머 |
| `p01/` | P01 엔진(127.0.0.1:8811), #6442 버전 디렉터리 + 롤백 스냅숏 |
| `b14/` | B14(127.0.0.1:8789) 유닛·드롭인·logrotate·ingress 템플릿 |
| `broker/`, `identity/`, `file-lane/`, `cron/`, `connector-watch/`, `offsite-backup/`, `restart-policy/` | 주변 서비스 |
| `boot-recovery/` | 호스트 재부팅 복구 |
| `deploy_from_main.sh` | **main 머지 후 컴2 반영** 표준 절차 (아래) |

## main 머지 후 컴2 반영 절차

2026-10-31 21:07 KST 전환 이후 `chat.padiem.net` 운영은 컴2(Chat 8798, P01 8811, B14 8789)다.
**main에 머지해도 컴2에는 자동 반영되지 않는다.** 아래 절차를 실행한다.

### 1) 운영 체크아웃과 스테이징 체크아웃을 분리한다 (최초 1회, 컴2 레인 수행)

지금은 운영과 스테이징이 같은 폴더(`/mnt/d/work/ai-revenue-lab-staging-chat`)를 공유한다.
배포 스크립트는 운영 전용 경로를 설정으로 받고, 두 경로가 같으면 `OPS_CHECKOUT_IS_STAGING`으로
거부한다. 실제 분리는 이 저장소가 아니라 컴2 레인이 한다.

```bash
# 예: 스테이징 클론에서 운영 전용 체크아웃을 하나 더 만든다 (경로는 컴2 레인이 결정)
git -C /mnt/d/work/ai-revenue-lab-staging-chat worktree add \
  /mnt/d/work/ai-revenue-lab-ops <main-sha>
```

운영 경로는 `PADIEM_COM2_OPS_CHECKOUT`(또는 `--ops-checkout`)로 넘긴다. 스테이징 경로는
`PADIEM_COM2_STAGING_CHECKOUT`에 남는다(기본값이 위 공유 경로다).

### 2) 계획만 확인한다 (기본값, 아무것도 바꾸지 않는다)

```bash
sudo env PADIEM_COM2_OPS_CHECKOUT=/mnt/d/work/ai-revenue-lab-ops \
  PADIEM_COM2_CHAT_DB=/mnt/d/padiem/chat-com2/chat.sqlite3 \
  bash /mnt/d/work/ai-revenue-lab-ops/deploy/host-com2/deploy_from_main.sh <main-sha>
```

출력: `MODE=DRY_RUN`, `SHA`, `PREVIOUS`, 바뀐 경로마다 `CHANGED=…`, `SERVICES=chat,p01`,
`PENDING_MIGRATIONS`, 마지막 한 줄 `SUMMARY=chat:WOULD_DEPLOY p01:SKIP b14:SKIP`.

- `<main-sha>`는 **origin/main과 정확히 같아야 한다**. 다르면 `SHA_NOT_ORIGIN_MAIN`으로 멈춘다.
- 체크아웃에 추적 파일 변경이 있으면 `--apply`가 `CHECKOUT_DIRTY`로 멈춘다.
- 새 마이그레이션이 있으면 아래 3)에서 멈춘다.

### 3) 새 마이그레이션이 있으면 먼저 적용한다

`apps/padiem-chat/migrations/`의 파일 중 운영 DB의 `padiem_local_migration_ledger`에 없는 것이
하나라도 있으면, 스크립트는 코드를 옮기지 않고 `MIGRATION_FIRST`와 `마이그레이션 먼저:`를 출력하고
exit 3으로 멈춘다. Chat 호스트는 시작할 때 대기 마이그레이션을 스스로 적용하므로, 운영 DB에는
검토된 절차로 먼저 적용한 뒤 이 명령을 다시 실행한다. DB를 읽을 수 없으면 `--apply`는
`CHAT_DB_UNREADABLE`로 멈춘다(없다고 가정하지 않는다).

### 4) 반영한다 (--apply)

```bash
sudo env PADIEM_COM2_OPS_CHECKOUT=/mnt/d/work/ai-revenue-lab-ops \
  PADIEM_COM2_CHAT_DB=/mnt/d/padiem/chat-com2/chat.sqlite3 \
  bash /mnt/d/work/ai-revenue-lab-ops/deploy/host-com2/deploy_from_main.sh <main-sha> --apply
```

바뀐 경로에 해당하는 서비스만 다시 설치한다: `apps/padiem-chat/`·`packages/` → chat,
`apps/padiem-ai-engine/` → p01, `apps/korean-ai-platform/` → b14. 서비스마다 **정지 → 재설치 →
기동 → health** 순서이고, 실패하면 직전 버전으로 되돌린다.

- chat: `PADIEM_COM2_PREVIOUS_DIR/<old-sha>` 체크아웃으로 다시 설치한다(`install.sh`가 그 체크아웃을
  가리키는 링크를 만든다).
- p01: #6442 설치기가 `/opt/padiem/p01/rollback/`에 남긴 스냅숏으로 `app` 링크를 되돌린다.
- b14: `/opt/padiem/b14/app`이 링크면 이전 체크아웃으로 되돌리고, 복사본이면
  `B14_ROLLBACK=MANUAL`로 멈춘다(되돌리기는 운영자 몫이다).

마지막 한 줄이 결과다: `SUMMARY=chat:PASS p01:SKIP b14:SKIP` (`PASS`/`ROLLBACK`/`ROLLBACK_FAILED`/`SKIP`).
되돌림이 일어나면 exit 1이다. 운영 체크아웃은 배포 SHA에 그대로 남으므로, 서비스별로 어느 버전이
살아 있는지는 `SUMMARY`와 `PREVIOUS_CHECKOUT`으로 확인한다.

### 설정

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `PADIEM_COM2_OPS_CHECKOUT` | 없음(필수) | 운영 전용 체크아웃 |
| `PADIEM_COM2_STAGING_CHECKOUT` | `/mnt/d/work/ai-revenue-lab-staging-chat` | 스테이징 경로(같으면 거부) |
| `PADIEM_COM2_STATE_DIR` | `/var/lib/padiem-com2-deploy` | 실행 사본 보관 |
| `PADIEM_COM2_PREVIOUS_DIR` | `/opt/padiem/com2-deploy/previous` | root 소유·서비스 읽기 가능한 직전 체크아웃 |
| `PADIEM_COM2_CHAT_HEALTH_ATTEMPTS` | `31` | Chat 기동 health 확인 횟수 |
| `PADIEM_COM2_CHAT_HEALTH_INTERVAL` | `2` | Chat health 재시도 간격(초) |
| `PADIEM_COM2_CHAT_HEALTH_TIMEOUT` | `60` | Chat health 전체 대기 상한(초) |
| `PADIEM_COM2_CHAT_DB` | `/mnt/d/padiem/chat-com2/chat.sqlite3` | 마이그레이션 원장을 읽는 운영 DB |
| `PADIEM_COM2_P01_APP` | `/opt/padiem/p01` | P01 설치 루트 (`app`, `rollback/`) |
| `PADIEM_COM2_B14_APP` | `/opt/padiem/b14/app` | B14 앱 체크아웃 |
| `PADIEM_COM2_SYSTEMCTL` / `_PYTHON` / `_GIT` | `systemctl` / `python3` / `git` | 래퍼 경로 |
| `PADIEM_COM2_CHAT_HEALTH_URL` 등 | 루프백 URL | 헬스 프로브 주소 |

`--apply`는 Linux·root·systemd를 요구한다. dry-run은 root 없이 돌지만, 체크아웃을 옮기는
스크립트가 자기 자신을 읽지 않도록 `STATE_DIR`에 사본을 만든다(그래서 쓰기 가능해야 한다). P01의 `app` 링크가 가리키는 실제 코드와 대상 Git 트리를 비교하며, 일치하지 않거나 확인할 수 없으면 P01을 건너뛰지 않는다. Chat health는 기본 2초 간격으로 최대 31회, 전체 60초 이내로 확인한다. 직전 코드 디렉터리는 서비스가 읽고 통과할 수 있어야 하며 서비스에 쓰기 권한은 주지 않는다.

### 하지 않는 것

`.env`·비밀 값 수정, Cloudflare·터널·DNS 변경, Windows `18731` 릴리스, `systemctl enable`,
마이그레이션 자동 적용, 스테이징 체크아웃 이동. 이 스크립트는 배포만 하고 배포 결과를 문서에
기록하지 않는다.

### 테스트

```bash
python -m pytest deploy/host-com2/tests -q
```

임시 git 저장소와 가짜 서비스(설치기·health·systemctl)로 dry-run, apply, 롤백, 마이그레이션 감지
멈춤을 실행한다. 실제 호스트·systemd·COM2에는 접속하지 않는다.
