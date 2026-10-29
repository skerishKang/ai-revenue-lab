# #5643 정리안 — 레거시 Mesh 터널 작업·supervisor 폐기 (2026-10-29)

```text
DOC_ROLE=MESH_TUNNEL_RETIREMENT_PLAN
STATUS=정리안(문서만) / 실행은 Qoder·운영 승인 후, 이 PR은 아무것도 삭제·변경하지 않음
ISSUE=#5643 (관련 #5578, #5015, #5573)
전제: 2026-10-23 20:58 KST 관측 — COM1 Mesh Agent가 192.168.0.101:4443으로 직접 TCP 연결,
      PADIEM-Mesh-Tunnel은 Settings.Enabled=false이나 State=Running(중지·제거의 증거 아님).
```

## 1. 사전 재확인 (제거 전 필수, 읽기 전용)

Qoder가 COM1/COM2에서 기록하고, 그 결과가 좋을 때만 §4를 시작한다.

1. COM1: Mesh Agent 프로세스가 여전히 `192.168.0.101:4443`에 **직접** 연결돼 있는지
   (`Get-NetTCPConnection -OwningProcess <MeshAgent PID>`), 시작 시각.
2. 제품 연결: 승인된 목록/읽기 시나리오 1회가 정상인지(대표 확인 경로).
3. COM2: `meshcentral` 서비스 active, loopback 443/4443 리스너 소유 프로세스.
4. `PADIEM-Mesh-Tunnel` 작업 상태·마지막 실행·PID, supervisor 프로세스/자식 `ssh.exe` 유무,
   포트 4443에 **구 supervisor가 잡고 있는 리스너가 있는지**(있으면 §4-2에서 정지·기록).
5. 산출물 백업: `Export-ScheduledTask -TaskName 'PADIEM-Mesh-Tunnel'`(UTF-16), 현재
   `MeshAgent.msh` 사본, supervisor 로그/상태 JSON. 값을 PR에 싣지 않는다.

기록 형식(수치·시각·PID만): `PRECHECK direct_conn=yes|no mesh_agent=running|stopped …
tunnel_task=Disabled|Ready|Running supervisor=pid|none listener=pid|none`.

## 2. 인벤토리 — 무엇이 터널 전용인가

### 2.1 소스 (`scripts/ops/com2_mesh/`)

| 파일 | 터널 참조 | 처분 |
|---|---|---|
| `com2_mesh_tunnel_supervisor.ps1` (593행) | 파일 전체 | **삭제** |
| `com2_mesh_tunnel_supervisor_selftest.ps1` (511행) | 파일 전체 | **삭제** |
| `com2_mesh_tunnel_task.template.xml` (54행) | 작업 정의 전체 | **삭제**(백업 XML은 운영 측에 남는다) |
| `com2_mesh_task_template.ps1` | 터널 XML 렌더·검증(3참조) | **삭제**(용도가 터널 작업뿐) |
| `com2_mesh_config.template.json` | 15참조: `tunnel_task`, `tunnel_local_host/port`, `tunnel_process_name`, `tunnel_supervisor_script`, `tunnel_restart_wait_seconds`, `tunnel_lock/state/log/ssh_*` | 터널 키 **삭제**, mesh 키 유지 |
| `com2_mesh_autostart.ps1` | 45참조: 체크 15개 중 **7개**(`tunnel_task_exists/_enabled/_autostart_trigger/_repetition_unbounded/_next_run_present/_ran_after_boot/_last_result_ok`) + 리스너 3개(`tunnel_listener_present/_process_matches/_started_after_boot`) | 터널 관련 **10개 제거**, 나머지 5개(`boot_time_observed`, `mesh_agent_running`, `_since_boot`, `_automatic`, `mesh_http_200`) 유지. `auto_start_verified`는 5개 기준으로 재정의 |
| `com2_mesh_autostart_selftest.ps1` | 71참조 | 터널 체크·config 키 기대값 **제거·재작성** |
| `com2_mesh_recovery.ps1` (1194행) | 32참조: `tunnel_listener_down`/`tunnel_broken` 분류, `restart_tunnel` 조치, `tunnel_*` 필수 키 | **터널 분류·조치 제거**, mesh 서비스 복구(`start_keeper`, `restart_mesh_service`, 프로브·record_only) 유지 |
| `com2_mesh_recovery_selftest.ps1` (819행) | 91참조 | 터널 시나리오 **제거**, mesh 시나리오 유지 |
| `com2_mesh_health_display.ps1` / `com2_mesh_health_patch.ps1` | 0 | 유지 |
| `com2_mesh_health_display_selftest.ps1` | 12참조 | 터널 표기 기대값 제거 |

### 2.2 운영 측(호스트, 저장소 밖)

| 위치 | 항목 | 처분 |
|---|---|---|
| COM1 | 예약 작업 `PADIEM-Mesh-Tunnel` | **Unregister**(먼저 `Stop-ScheduledTask`, 실행 중 supervisor·자식 종료 확인) |
| COM1 | supervisor 배포본·lock/state/log 파일 | 실행 정지 후 **폐기**(백업 후) |
| COM1 | `MeshAgent.msh`(.bak-20261023 포함) | **유지** — 롤백 경로 |
| COM2 | portproxy `192.168.0.101:4443 → 127.0.0.1:4443`, 방화벽 `PADIEM-Mesh-4443-from-COM1` | **당분간 유지** — 직접 연결의 현재 경로이자 롤백 경로. 별도 검토 후 결정 |
| COM2 | Mesh 서비스(`meshcentral`)·health | **유지** |

### 2.3 문서

- `docs/operations/COM2_MESH_AUTO_RECOVERY_HARDENING_20261023.md` — §2.2(supervisor)·§2.3(작업 XML)·자동 시작 체크 목록·운영 적용 절차에서 터널 부분을 **폐기 표시**로 갱신하고 #5643 링크.
- `docs/operations/MESH_FAILOVER_ORACLE_COM2_20261021.md`, `PADIEM_CLAW_5015_COM2_PRO_ACCEPTANCE_20261019.md` — 역사 기록은 유지하되 "터널 경로는 #5643으로 폐기됨" 배너 1줄.

## 3. 유지·교체 요약

- 유지: Mesh Agent, COM2 Mesh 서비스, 포트프록시/방화벽(롤백 경로), 복구 엔진의 mesh 서비스 조치, health display, `com2_mesh_autostart`의 mesh 5체크, 공용 health/recovery.
- 교체: `auto_start_verified` 정의를 **5체크 기준**으로 축소(터널이 없으므로 "부팅 후 mesh 도달"만 본다).

## 4. 제거 순서 (Qoder, 승인 창)

1. §1 재확인 기록 — 하나라도 실패면 중단·CTO 보고.
2. COM1: 작업 `PADIEM-Mesh-Tunnel` `Stop-ScheduledTask` → 실행 중 supervisor/자식 `ssh.exe` 종료(포트 4443 리스너가 이 자식 소유인지 확인) → `Unregister-ScheduledTask`(+ `Export-ScheduledTask` 백업 확인).
3. 소스 변경(별도 PR): §2.1 표대로 삭제·축소, selftest 3종 재실행(자동 시작·복구·health display).
4. 운영 배포본 교체(COM1/COM2 운영 디렉터리) — 실제 파일만, 서비스 재시작 없이.
5. 재검증: §1의 2·3이 그대로인지, `AutoStart` 관측이 새 5체크로 `verified|failed|unverified`를 정직하게 내는지.
6. 문서 갱신(§2.3).

## 5. 롤백

- 백업한 작업 XML 재등록 + supervisor 배포본 복원 + `MeshAgent.msh` 복원(dated backup) → Agent 재시작 → 재연결 확인. 이 저장소의 변경은 revert PR로 되돌린다.
- 롤백도 §1 재확인으로 끝맺는다.

## 6. 수용 기준 매핑 (#5643)

| 기준 | 증거 |
|---|---|
| 직접 Mesh 연결·제품 연결 유지 | §1-1·§1-2를 제거 전/후 각각 기록, 동일 결과 |
| 폐기 작업·supervisor가 스케줄/실행되지 않음 | `Get-ScheduledTask PADIEM-Mesh-Tunnel` → 없음, 포트 4443 리스너 소유 프로세스가 supervisor 자식 아님 |
| 유지된 #5578 책임 문서화 | §3 + 갱신된 hardening 문서 |

## 7. 이 PR이 하지 않는 것

- 어떤 호스트 설정·파일·작업도 변경·삭제하지 않는다. 소스 삭제는 §1 재확인 후 별도 코드 PR, 운영 제거는 Qoder가 승인 창에서 수행한다.
