# COM2 재시작 창·Chat 백업 — 1장 운영 절차 (2026-11-08)

```text
DOC_ROLE=COM2_RESTART_AND_BACKUP_ONE_PAGE
STATUS=컴2 실측 완료(설정·백업 시험) / 저장소 반영은 PR, 재부팅 실험은 하지 않음
RELATED=deploy/host-com2/chat/(backup.py, timer), deploy/host-com2/offsite-backup/,
        deploy/host-com2/boot-recovery/windows/check-active-hours.ps1,
        docs/operations/COM2_BOOT_RECOVERY_RUNBOOK.md,
        docs/operations/COM2_OFFSITE_BACKUP_RUNBOOK.md,
        docs/operations/CHAT_COM2_RUNBOOK.md §9
경계: 이 문서의 명령은 컴2에서만 실행한다. 저장소 PR은 컴2를 바꾸지 않는다.
```

## 1. Windows 자동 재시작 창

대표 결정(2026-11-08): 자동 재시작을 새벽으로 고정한다.

| 항목 | 값 (2026-11-08 적용 후 실측) | 되돌리기 |
| --- | --- | --- |
| `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings\ActiveHoursStart` | `10` (이전 `8`) | `-StartHour 8` |
| `…\ActiveHoursEnd` | `4` (이전 `17`) | `-EndHour 17` |
| `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU\NoAutoRebootWithLoggedOnUsers` | `0` (이전 `1`) | `-NoAutoRebootWithLoggedOnUsers 1` |
| 결과 재시작 가능 창 | **04:00–10:00** | |

```powershell
# 컴2에서, 관리자 PowerShell. dry-run이 기본이다.
deploy\host-com2\boot-recovery\windows\check-active-hours.ps1
deploy\host-com2\boot-recovery\windows\check-active-hours.ps1 -Apply

# 원복(2026-11-08 이전 값)
… -Apply -StartHour 8 -EndHour 17 -NoAutoRebootWithLoggedOnUsers 1
```

- **1시간 고정은 지원되지 않는다.** Windows 활성 시간의 상한은 18시간이라 재시작 창의 최소 폭이 6시간이다. 활성 10:00–04:00이 창을 04:00에 시작시키는 가장 가까운 설정이고, Windows Update는 활성 시간이 끝난 뒤 첫 기회에 재시작하므로 실제 재시작은 04:00 무렵에 온다.
- `NoAutoRebootWithLoggedOnUsers=1`이면 로그인한 콘솔 세션이 있는 한 야간 재시작이 오지 않는다(컴2은 데스크톱 세션이 떠 있다). 그래서 창을 살리려면 `0`이어야 한다.
- 백업과의 관계: chat 스냅샷 04:20·offsite 05:10은 `Persistent=true`라 재시작으로 놓쳐도 부팅 뒤 따라잡는다. Windows 작업 `PADIEM-COM2-D1-R2-Sync`(04:20)는 따라잡기(`StartWhenAvailable`)가 없어, 재시작이 04:20을 넘긴 날은 그날 D1 세대가 하루 전 것이 된다. offsite는 26시간 신선도 상한 안이라 그 실행은 여전히 통과한다(이 PR은 그 작업을 바꾸지 않았다).

## 2. 절전·최대 절전 (조치 불필요, 실측)

| 설정 | 실측 (AC) | 뜻 |
| --- | --- | --- |
| 대기(standby) | `0` | 절전 안 들어감 |
| 최대 절전(hibernate idle) | `0` | 최대 절전 안 들어감 |
| `HKLM\SYSTEM\CurrentControlSet\Control\Power\HibernateEnabled` | `0` | 최대 절전 꺼짐(빠른 시작도 적용되지 않음) |
| 디스플레이 끄기 | `0` | 화면도 안 꺼짐 |

- 확인: `powercfg /q SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`, `powercfg /q SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE`, `powercfg /q SCHEME_CURRENT SUB_VIDEO VIDEOIDLE`.
- 되돌리기: `powercfg /change standby-timeout-ac <분>`, `powercfg /hibernate on`.

## 3. 로그인 없이 부팅 후 WSL·서비스 기동 (이미 되어 있음 — 증거)

| 증거 | 실측 (2026-11-08) |
| --- | --- |
| 예약 작업 `\PADIEM-Mesh-WSL-KeepAlive` | Trigger `BootTrigger`, Principal `S4U`(대화형 로그온 불요), `HighestAvailable`, `RestartOnFailure 3×1m`, 실행 `C:\Users\user\padiem-wsl-keepalive.cmd` |
| keepalive 로그 | Windows 부팅 `2026-11-06 07:51` 직후 `07:51:20 START` |
| WSL systemd | `/etc/wsl.conf` `[boot] systemd=true`, `systemctl is-system-running` = `running` |
| 서비스 자동 시작 | 아래 9개 모두 `enabled`+`active` (chat-com2, oracle-mesh-executor, mesh-queue, meshcentral, b14, p01, file-lane, cloudflared-padiem, boot-recovery) |
| 부팅 자가 점검 | `padiem-boot-recovery.service` 마지막 실행 `BOOT_RECOVERY=PASS failures=0` |
| 감시 작업 | `PADIEM-Mesh-WSL-KeepAlive-Watchdog2` 1분 주기, `PADIEM-COM2-Runtime-Supervisor` 5분 주기 |

- 재확인: `schtasks /query /tn PADIEM-Mesh-WSL-KeepAlive /xml`에서 `<BootTrigger>`·`<LogonType>S4U</LogonType>`; WSL에서 `systemctl is-enabled <unit>`; `journalctl -u padiem-boot-recovery.service -n 20`.

## 4. Chat DB 백업 (매일 1회, 서비스 무정지)

| 항목 | 값 |
| --- | --- |
| 유닛 | `padiem-chat-com2-backup.timer`(예약) → `padiem-chat-com2-backup.service`(실행) |
| 주기 | 매일 **04:20** (`OnCalendar=*-*-* 04:20:00`, `Persistent=true`) |
| 원본 | `/mnt/d/padiem/chat-com2/chat.sqlite3` |
| 보관 | `/mnt/d/padiem/chat-com2/backups/chat-<UTC stamp>.sqlite3`, **7일분** 회전 |
| 방식 | `VACUUM INTO`(엔진 내 일관 스냅샷, 서비스 정지 없음) → 사본 `PRAGMA integrity_check` + 4표 행 수 대조 통과 후에만 이전 것을 지운다 |
| 실행 사용자 | `padiem-chat` |

```bash
sudo systemctl start padiem-chat-com2-backup.service      # 수동 1회
systemctl show -p Result -p ExecMainStartTimestamp padiem-chat-com2-backup.service
journalctl -u padiem-chat-com2-backup.service -n 5 --no-pager -o cat
ls -1t /mnt/d/padiem/chat-com2/backups/chat-*.sqlite3 | head
```

2026-11-08 수동 실행 실측:

```text
Result=success
CHAT_COM2_BACKUP=PASS file=chat-20261108T122245Z.sqlite3 removed=1 users=59 conversations=958 messages=2694 projects=5
PRAGMA integrity_check=ok   PRAGMA quick_check=ok   COUNT=7
```

## 5. 기기 밖 사본 (R2, 암호화)

| 항목 | 값 |
| --- | --- |
| 유닛 | `padiem-offsite-backup.service` (+ `.timer`, 매일 05:10, `Persistent=true`) |
| 올리는 대상 | chat·queue·d1-chat·d1-engine (broker는 이 호스트에 없어 `NOT_INSTALLED`, 실패 아님) |
| 암호화 | PADIEM-CBE1(AES-256-GCM), 키 파일은 컴2에만(0600) — R2에 없다 |
| 최근 실행 | 2026-11-08 05:10 `OFFSITE_RUN=PASS UPLOADED=4 FAILED=-`, `chat STATUS=OK` |

- 컴1 복사 대신 **R2**를 쓰는 이유: 이미 매일 돌고 있고, 암호문만 나가며, 컴1이 꺼져 있어도 사본이 남는다.

## 6. 복원

### 6-1. 로컬 스냅샷으로 되돌리기 (전체 절차: CHAT_COM2_RUNBOOK.md §9)

```bash
sudo systemctl stop padiem-chat-com2.service
sudo -u padiem-chat sh -c 'cd /mnt/d/padiem/chat-com2 && mv chat.sqlite3 chat.sqlite3.pre-restore-$(date -u +%Y%m%dT%H%M%SZ) && rm -f chat.sqlite3-wal chat.sqlite3-shm'
sudo -u padiem-chat cp /mnt/d/padiem/chat-com2/backups/chat-<stamp>.sqlite3 /mnt/d/padiem/chat-com2/chat.sqlite3
sudo -u padiem-chat /opt/padiem/chat-com2/venv/bin/python -c "import sqlite3;c=sqlite3.connect('/mnt/d/padiem/chat-com2/chat.sqlite3');print(c.execute('PRAGMA integrity_check').fetchone()[0],[(t,c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]) for t in ('users','conversations','messages','projects')])"
sudo systemctl start padiem-chat-com2.service
```

확인: `integrity_check`=`ok`, 4표 건수가 백업 로그의 `CHAT_COM2_BACKUP=PASS … users=… conversations=… messages=… projects=…`와 일치, 기동 후 로그인·대화 1건.

### 6-2. R2 사본으로 되돌리기 (상세: COM2_OFFSITE_BACKUP_RUNBOOK.md)

```bash
/opt/padiem/offsite-backup/venv/bin/python /opt/padiem/offsite-backup/offsite.py restore \
  --service chat --date <UTC-YYYYMMDD> --target /mnt/d/padiem/chat-com2/chat.sqlite3 --replace
```

`--replace` 없이 실행하면 검증만 하고 staging 파일을 남긴다. 기존 파일은 `<name>.pre-restore-<ts>`로 옆에 보존된다.

## 7. 백업 대상과 제외 (보고용)

- **대상**: `chat.sqlite3` 한 파일(스냅샷). WAL/SHM은 스냅샷에 포함되지 않는다.
- **제외(파일 자체를 백업하지 않음)**: `/opt/padiem/chat-com2/.env`, `/etc/padiem/offsite-backup.env`·`.key`, SSH 키, Cloudflare/R2 토큰, WSL root 자격.
- DB 안에는 인증에 필요한 해시·토큰 표(`password_credentials`, `password_reset_tokens`, `chat_custom_provider_credentials`, `padiem_mcp_tokens` 등)가 포함된다. 표를 빼면 복원한 서비스가 로그인을 못 하므로 전체 DB를 뜬다. 로컬 사본은 0700 디렉터리에만 있고, 기기 밖으로 나가는 것은 암호문뿐이다.

## 8. 이 페이지가 하지 않는 것

- 재부팅 시험(CTO 지시로 설정 확인까지만 했다).
- 서비스 재시작·중지(백업 1회 실행만 했다).
- Windows 예약 작업·BIOS·WoL 변경.
