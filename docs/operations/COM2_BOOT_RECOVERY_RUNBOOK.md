# COM2 정전·재부팅 자동 복구 런북 (#4953, 소프트웨어 부분)

```text
DOC_ROLE=COM2_BOOT_RECOVERY_RUNBOOK
STATUS=스크립트·유닛·테스트 준비 완료 / 컴2 설정·재부팅은 Qoder (배포 없음)
RELATED=deploy/host-com2/boot-recovery/, #4953, #6141(알림 이름)
경계: 이 런북의 어떤 단계도 이 저장소 PR로 자동 실행되지 않는다.
```

## 1. 목표와 경계

- 목표: 정전·Windows 업데이트 재부팅·WSL 종료 뒤 **사람 로그인 없이** 큐·실행기·MeshCentral·파일 레인·Chat·broker·cloudflared·감시·백업 타이머가 다시 뜨고, 실패하면 스스로 알린다.
- 소프트웨어: Windows 예약 작업(시스템 시작, SYSTEM) → WSL 안 `boot-recovery.sh` → systemd 대기 → 자가 점검 → 기록·알림.
- 하드웨어(BIOS·WoL)는 사람이 한다 — §2의 대표 체크리스트. 자가 점검은 BIOS 설정을 검증하지 않는다.

## 2. 대표(사람) 체크리스트 — BIOS/UEFI·WoL

확인 방법(컴2에서, 관리자 PowerShell):
```powershell
Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product,Version
Get-CimInstance Win32_BIOS | Select Manufacturer,SMBIOSBIOSVersion,ReleaseDate
```
- [ ] **Restore on AC Power Loss / AC Back** = `Power On`(또는 `Last State`가 아니라 Power On)으로 설정. (제조사별 명칭: ASUS "Restore AC Power Loss", MSI "Power Management Setup → Restore after AC Power Loss", Gigabyte "AC BACK", Dell "AC Recovery")
- [ ] **RTC Alarm / Wake on RTC** 필요 시: 매일 지정 시각(예: 07:00) 켜짐. 시각은 대표 일정과 충돌 없는 값으로 확정.
- [ ] **Wake-on-LAN**: UEFI에서 "Power On By PCI-E/PCI" 또는 "ErP" 비활성(ErP 켜면 WoL 불가). Windows NIC 전원 관리에서 "이 장치로 컴퓨터를 깨울 수 있음" 허용.
- [ ] 검증(승인된 창): 정전 모의는 벽 전원 차단 30초 → 복전 → 무인 부팅 확인. WoL은 **같은 LAN**에서 먼저. 외부 WoL은 승인된 VPN/관리 채널로만, 무인증 포트 개방 금지.
- 확인 결과/대체: 하드웨어가 AC 복구를 지원하지 않으면 그 사실과 대체안(RTC, 수동 전원 후 자동 복구는 소프트웨어가 담당)을 기록한다.

## 3. Windows 측 (Qoder, dry-run 먼저)

1. **활성 시간**(자동 재부팅 회피): 기본 기대값 **활성 00:00–18:00 → 재부팅 가능 창 18:00–24:00**. 야간 백업(04:10~05:10)과 오프사이트 업로드(05:10)를 피한다.
   ```powershell
   .\windows\check-active-hours.ps1              # ACTIVE_HOURS=MISSING/MISMATCH면
   .\windows\check-active-hours.ps1 -Apply       # 레지스트리 기록
   ```
2. **.wslconfig / systemd 점검**:
   ```powershell
   .\windows\check-wslconfig.ps1                 # MISSING → 권장 블록 출력
   .\windows\check-wslconfig.ps1 -Apply          # 기존 파일은 건드리지 않음(없을 때만 생성)
   ```
   권장: `[wsl2]` `vmIdleTimeout=9223372036854775807`(사실상 무제한). Distro의 `/etc/wsl.conf`에 `[boot] systemd=true` 필수(이미 서비스가 systemd로 돌고 있다면 충족).
3. **부팅 예약 작업 등록**(로그인 불요):
   ```powershell
   .\windows\register-boot-task.ps1              # DRY_RUN: action/trigger/principal만 출력
   .\windows\register-boot-task.ps1 -Apply       # Register-ScheduledTask (AtStartup, SYSTEM)
   ```
   - 기본값 `-Distro Ubuntu -WslUser root -Script /opt/padiem/boot-recovery/boot-recovery.sh`.
   - 검증: `Get-ScheduledTask PadiemBootRecovery | fl State,Triggers` → Ready. **승인된 재부팅 창에서 1회 실증** 후 journal 확인(§5).
   - SYSTEM 실행이 distro를 못 찾는 환경이면(배포판이 사용자별 등록) 대안: 서버 계정으로 "로그온 여부와 관계없이 실행" 작업 + 자동 로그온은 **하지 않는다** — Qoder가 실제 결과를 보고 CTO에 보고.

## 4. WSL 측 설치 (Qoder)

```bash
cd deploy/host-com2/boot-recovery
./install.sh                      # DRY_RUN
sudo ./install.sh --apply         # 설치만(시작/enable 없음)
sudo $EDITOR /opt/padiem/boot-recovery/.env     # B66_ALERT_* 이름 채우기(값 비노출)
sudo $EDITOR /opt/padiem/boot-recovery/units.json  # MeshCentral/cloudflared 실제 유닛명 확인·수정
sudo systemctl enable padiem-boot-recovery.service
sudo systemctl start padiem-boot-recovery.service   # 즉시 1회 점검(선택)
```

- `units.json`: 기본값은 저장소 유닛 이름 + 외부 `cloudflared.service`·`meshcentral.service`. **실제 이름이 다르면 여기만 고친다**(스크립트 수정 금지). 매일 안 쓰는 유닛이면 `required:false`로 내려 소음 없이 보고만.
- 알림: `B66_ALERT_TELEGRAM_BOT_TOKEN`/`_CHAT_ID`, `B66_ALERT_DISCORD_WEBHOOK_URL`(#6141과 동일 이름). 없으면 `BOOT_RECOVERY_NOTIFY=not_configured`만 남고 성공을 가장하지 않는다.

## 5. 부팅 검증(승인된 창)

1. 재부팅 후 로그인하지 않은 상태로 3~5분 대기.
2. `journalctl -u padiem-boot-recovery.service -n 40` → `BOOT_RECOVERY=PASS`(또는 FAIL 목록).
3. `/var/lib/padiem/boot-recovery/last.json`(0600)에서 유닛/health/터널 판정 확인.
4. 공개 경로: `https://chat.padiem.net/health`가 `{"status":"ok"}`.
5. WSL 유휴 종료 방지 확인: 로그인 없이 30분 뒤 `wsl.exe -l --running`에 distro가 남아 있는지(Qoder 실측).
6. 실패 시: `BOOT_RECOVERY_FAIL unit:…`/`health:…`/`tunnel:…`가 알림으로 온다. 유닛 하나가 inactive면 그 유닛의 `systemctl status`가 다음 조치다(이 킷은 아무것도 재시작하지 않는다).

## 6. 원복

- 예약 작업: `Unregister-ScheduledTask -TaskName PadiemBootRecovery -Confirm:$false`
- WSL 자가 점검: `systemctl disable --now padiem-boot-recovery.service`; `/opt/padiem/boot-recovery`는 남겨도 무해.
- 활성 시간: 원래 값으로 되돌리려면 `-StartHour/-EndHour`를 실제 원 값으로 지정해 `-Apply`.
- `.wslconfig`: `-Apply`가 만든 경우에만 파일 삭제(기존 파일은 건드리지 않았다).

## 7. Qoder 인계 목록

1. 대표 BIOS 체크리스트(§2)를 대표 일정에 맞춰 수행·기록 — 코드 작업 아님.
2. Windows: `check-active-hours.ps1 -Apply`, `check-wslconfig.ps1`(권장 블록 반영), `register-boot-task.ps1 -Apply`.
3. WSL: `install.sh --apply` → `.env`(B66_ALERT_*)·`units.json`(실제 유닛명) → `systemctl enable`.
4. 승인 창 재부팅 1회로 §5 검증, 결과(PASS/FAIL·실패 항목·마지막 재부팅 시각)를 CTO에 보고.
5. 실패 알림이 왔다면 어떤 유닛/health/터널인지와 `systemctl status` 요지를 함께 보고.
