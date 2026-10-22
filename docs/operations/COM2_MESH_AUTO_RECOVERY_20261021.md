# COM2 MeshCentral 장애 감지·자동 복구 (2026-10-21)

- 구현: `scripts/ops/com2_mesh/com2_mesh_recovery.ps1`, `scripts/ops/com2_mesh/com2_mesh_recovery_selftest.ps1`
- 설정 예시: `scripts/ops/com2_mesh/com2_mesh_config.template.json`
- 관련: `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` (다른 런타임 감독기, 이 문서가 변경하지 않음)
- 후속: `docs/operations/COM2_MESH_AUTO_RECOVERY_HARDENING_20261023.md` (bounded retry·원격 원인 구분·터널 감독기·자동 시작 실측, 소스만 반영)
- 상태: **ENGINE_IMPLEMENTED / FIXTURE_SELFTEST_PASSED / OPERATIONAL_DEPLOY_LIVE_VERIFIED**

## 1. 장애 사례

2026-10-21 관측값:

```text
00:00:06  MeshCentral HTTP 200 via tunnel          healthy
00:05:05  MeshCentral HTTP 000 via tunnel          FAULT
00:35:05  MeshCentral HTTP 200 via tunnel          RECOVERY
```

- 장애 30분 동안 COM1의 SSH 전달 프로세스, COM2 WSL의 MeshCentral 유닛, keeper 프로세스는 모두 살아 있었다.
- COM1 loopback 리스너는 열려 있었고, 그 리스너를 통과한 HTTP 응답만 000이었다.
- SSH 로컬 포워딩은 하나의 전송 위에 연결별 채널을 다중화한다. 로컬 리스너가 열려 있다는 사실은 원격 경로가 응답한다는 증거가 아니다.
- 그 시점의 모니터는 원격 측을 조회하지 않았고 복구 조치도 없었다. 그래서 같은 FAULT 문구가 30분 동안 반복되었고, 경로가 스스로 회복된 뒤에야 RECOVERY가 기록되었다.
- 장애 중 COM2 원격 프로브 값은 남아 있지 않다. 당시 모니터가 원격을 조회하지 않았으므로, 30분 정지의 최종 원인을 로컬 전달 계층과 원격 서비스 계층 중 하나로 확정할 수 없다. 새 엔진은 다음 발생 시 이 구분을 기록한다.

## 2. 함께 고친 결함

| 결함 | 확인된 상태 | 수정 |
|---|---|---|
| COM2 watchdog의 keeper 탐지 | Windows `tasklist`로 Linux 프로세스 이름을 찾아 항상 미검출, 매 실행 `KEEPALIVE_MISSING_STARTING` 기록 | WSL 안에서 `pgrep`으로 탐지 |
| COM2 watchdog의 재시작 경로 | 보조 작업이 Disabled 상태여서 `schtasks /run`이 실패 | 등록된 작업 경로를 정확히 사용하고, 작업이 비활성일 때는 WSL 안에서 keeper만 시작 |
| COM1 원격 프로브 | SSH 호출에 명령 타임아웃이 없어 응답 없는 `ssh.exe`가 남을 수 있음 | 모든 원격 호출을 제한 시간 내 종료, 초과 시 프로세스 종료 |

## 3. 구성

```text
COM1 health task (5분)
  └─ com2-mesh-health.ps1
       ├─ 로컬 프로브 3종 (COM2 SSH TCP, COM1 tunnel TCP, MeshCentral HTTP)
       ├─ 원격 프로브 1종 (COM2에서 HTTP/KEEPER/UNIT 1줄 출력, 명령 타임아웃 필수)
       ├─ com2_mesh_recovery.ps1  (분류 → 단일 조치 → HTTP 200 검증)
       ├─ com2-mesh-status.json / .html  (기존 필드 + 분류·조치·복구 필드)
       ├─ com2-mesh-health.log  (항상 기록)
       └─ com2-mesh-alert.ps1   (기존 파일 그대로, 복구 전 최초 프로브 값 전달)
```

COM2 쪽 probe는 `HTTP=<3자리>;KEEPER=OK|MISSING|UNKNOWN;UNIT=active|inactive|failed|unknown` 한 줄만 출력한다. 값 판정과 조치 결정은 COM1 엔진이 한다.

## 4. 분류와 조치 계약

| 분류 | 조건 | 조치 |
|---|---|---|
| `healthy` | MeshCentral HTTP 200 | 없음 |
| `com2_ssh_unreachable` | COM2 SSH TCP 실패 | 기록만 |
| `tunnel_listener_down` | COM1 loopback 전달 포트 미수신 | `restart_tunnel` |
| `tunnel_broken` | 원격 HTTP 200, 로컬 HTTP 000 | `restart_tunnel` |
| `com2_mesh_down` | 원격 HTTP 200 아님 | keeper `MISSING` → `start_keeper`; 유닛 `active` 아님 → `restart_mesh_service`; 둘 다 정상 → 기록만 |
| `remote_probe_failed` | COM2 도달 가능, 원격 프로브 실패 | 기록만 |

원격 원인 구분(2026-10-23 추가): `remote_probe_failed`는 `remote_cause`로 세분한다. 허용 값은 `ssh_timeout`, `ssh_connect_timeout`, `ssh_auth_failed`, `ssh_connection_refused`, `ssh_network_unreachable`, `ssh_transport_error`, `probe_script_failed`, `probe_no_verdict`, `ssh_client_missing`, `not_probed`, `fixture_remote_probe_failed`다. HTTP 000만으로는 COM2 유닛을 재시작하지 않는다. 원격 유닛·keeper 값을 직접 관측하지 못한 경우 `com2_state_source=unverified`로 기록하고 `record_only`로 처리한다. 값이 `unknown`일 때 `restart_mesh_service`·`start_keeper`를 계획하지 않는다.

조치 정의:

- `restart_tunnel`: 설정된 전달 작업을 중지·시작하고, 설정된 loopback 포트를 소유한 잔여 전달 프로세스만 종료한다. 포트 소유 프로세스의 이름과 명령줄이 설정된 전달과 일치할 때만 종료하며, 다른 프로세스가 포트를 점유하면 중지하고 실패로 기록한다.
- `start_keeper`: WSL 안에서 keeper 프로세스만 시작한다. 배포판을 중지하지 않는다.
- `restart_mesh_service`: WSL 안에서 설정된 MeshCentral systemd 유닛만 재시작한다. Windows MeshCentral 프로세스는 건드리지 않는다.
- `record_only`: 상태만 기록하고 다음 검사로 넘긴다.

복구 성공은 조치 후 실제 HTTP 200을 측정했을 때만 기록한다. 200이 아니면 마지막 HTTP 코드, 실패 원인, 다음 검사 시각을 남긴다.

동시 실행 방지:

- `lock_file`은 PID와 시작 시각을 담는다. `recovery_lock_seconds` 이내이고 PID가 살아 있을 때만 유효하다.
- PID가 없거나 오래된 락은 인수한다. 다른 프로세스의 락은 지우지 않는다.
- 상태 파일은 `first_fault`를 보존한다. 조치 없이 200으로 돌아오면 `SELF_RECOVERED_HTTP_200`과 실제 경과 시간을 기록하고 `first_fault`를 비운다.

## 5. 기록 계약

health log 한 줄(`key=value`):

```text
check / mode / class / com2_ssh / tunnel_tcp / mesh_http / remote_http /
remote_keeper / remote_unit / remote_cause / com2_state_source / first_fault /
attempt / planned_action / action / executed / recovery_ok / recovery_at /
elapsed_sec / fault_age_sec / retry_decision / retry_attempt / retry_max /
next_attempt_at / recovery_state / class_started_at / class_age_sec /
remote_http_reason / pending_since / pending_action / pending_deadline /
pending_invalidation / http200_observed_at / http200_first_observed_sec /
http200_observed_basis / code / error / detail
```

요구 필드 대응:

| 요구 필드 | 기록 필드 |
|---|---|
| 검사 시각 | `check`, `ts` |
| COM2 SSH TCP | `com2_ssh` |
| COM1 터널 TCP | `tunnel_tcp` |
| MeshCentral HTTP | `mesh_http` |
| 최초 장애 감지 시각 | `first_fault` |
| 복구 시도 시각 | `attempt` |
| 실행 조치 | `planned_action`, `action`, `executed` |
| 복구 성공 확인 시각 | `recovery_at`, `recovery_ok` |
| 실제 경과 시간 | `elapsed_sec`, `fault_age_sec` |
| 실패 원인 | `error`, `detail`, `remote_cause` |
| 원격 상태 근거 | `com2_state_source` (`direct`/`unverified`) |
| 재시도 결정 | `retry_decision`, `retry_attempt`, `retry_max`, `next_attempt_at` (레코드·health log), `attempt_count`, `last_attempt_at`, `last_success_at` (상태 파일) |
| 검증 창 상태 | `recovery_state`, `pending_since`, `pending_action`, `pending_deadline`, `pending_invalidation`, `max_pending_seconds` (레코드·health log), `class_started_at`, `pending_since`, `pending_action`, `pending_deadline` (상태 파일) |
| 장애 시계 | `first_fault`, `fault_age_sec`(에피소드), `class_started_at`, `class_age_sec`(현재 class) |
| HTTP 200 관측 | `http200_observed_at`, `http200_first_observed_sec`, `http200_observed_basis` |
| 원격 HTTP 성질 | `remote_http_reason` (`remote_probe_failed`/`remote_http_code`/`remote_http_no_response`) |
| 오류 코드 | `code` |

동일 장애·동일 계획 조치(`class|planned_action`)의 재시도는 에피소드 단위로 제한한다. 기본값은 최대 3회, backoff 300/900/1800초, cooldown 300초, retry window 3600초다. healthy 또는 다른 조치가 필요한 분류로 바뀌면 에피소드를 초기화한다. Simulate/DryRun은 시도 횟수를 소모하지 않는다. 설정 키는 `recovery_max_attempts`, `recovery_backoff_schedule_seconds`, `recovery_cooldown_seconds`, `recovery_retry_window_seconds`다.

검증 창(`verify_timeout_seconds`, 기본 30초) 안에 HTTP 200이 없으면 조치는 실패가 아니라 pending이다. `max_pending_seconds`(기본 900초) 동안 새 조치를 억제하고, 만료될 때 시도 1회를 소모해 backoff로 들어간다. pending 중 200을 관측하면 `RECOVERED_HTTP200_OBSERVED_AFTER_PENDING`으로 복구를 기록하되 관측 시각을 복구 시각으로 쓰고 과거로 소급하지 않는다. class가 바뀌거나 같은 class에서 조치가 사라지거나 조치가 바뀌면 pending을 즉시 닫는다(`class_changed`/`class_not_actionable`/`action_changed`). 세부 계약은 `COM2_MESH_AUTO_RECOVERY_HARDENING_20261023.md` §3.4–§3.5.

`recovery_log`에는 같은 값이 한 줄 JSON(`schema=com2_mesh_recovery/v1`)으로 남는다. `status_file`은 마지막 레코드 전체를 담는다.

주요 코드: `HTTP_200`, `SELF_RECOVERED_HTTP_200`, `PLANNED_RESTART_TUNNEL`, `PLANNED_START_KEEPER`, `PLANNED_RESTART_MESH_SERVICE`, `RECOVERED_HTTP_200`, `RECOVERED_HTTP200_OBSERVED_AFTER_PENDING`, `RECOVERY_FAILED_HTTP_<code>`, `RECOVERY_PENDING_HTTP_<code>`, `RECOVERY_PENDING_AWAITING_VERIFY`, `RECOVERY_FAILED_PENDING_EXPIRED`, `RECOVERY_LOCKED`, `RECOVERY_BACKOFF`, `RECOVERY_RETRY_EXHAUSTED`, `COM2_SSH_UNREACHABLE`, `REMOTE_PROBE_FAILED`, `NO_ACTION_AVAILABLE`, `ENGINE_ERROR`.

`action` 값에는 조치 이름 외에 `skipped_backoff`(재시도 대기), `skipped_exhausted`(재시도 한도 소진), `skipped_locked`(다른 복구 프로세스 실행 중), `record_only`(조치 없음)가 기록된다.

## 6. 실행 방법

```powershell
# 정상 검사와 조치 실행
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery.ps1 -Config <config.json>

# 분류·계획만 확인 (조치 없음)
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery.ps1 -Config <config.json> -DryRun

# 모의 fixture 검증 (네트워크 프로브·조치 없음)
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery_selftest.ps1
```

설정 파일은 실행 호스트에만 둔다. 저장소에는 값이 없는 `com2_mesh_config.template.json`만 둔다. 실제 주소·계정·키 경로는 설정 파일과 운영 문서에 기록하지 않는다.

## 7. selftest 범위

- 분기: `healthy`, `tunnel_broken`, `tunnel_listener_down`, `com2_mesh_down`(keeper 없음), `com2_mesh_down`(유닛 비활성), `com2_mesh_down`(조치 없음), `com2_ssh_unreachable`, 원격 프로브 실패, 락 충돌, 오래된 락 인수.
- 각 분기의 분류·계획 조치·실행 조치·코드, 레코드 필드, health log 필드, 상태 파일, 락 처리.
- Simulate에서는 어떤 조치도 실행하지 않는다(`executed=false`, `code=PLANNED_*`).
- 첫 장애 시각 보존과 자기 회복 기록.
- Windows 인용 규칙(공백·따옴표·끝 백슬래시·빈 인수).
- 2026-10-23 추가: 원격 실패 원인별 분류, `unknown` 유닛·keeper에서 COM2 조치 미계획, `com2_state_source` 기록, 동일 에피소드 backoff·한도 소진·에피소드 초기화·Simulate 시도 미소모.
- 2026-10-23 통합 추가(#5577 f1fe620d에서 이식): pending 활성 중 조치 억제, pending 만료의 시도 1회 소비와 backoff, 만료 예산 소진, pending 중 200 관측과 비소급 기록, class 변경·비조치 class·조치 변경에서 pending 폐기(누수 없음), 에피소드 시계와 class 시계 분리.

## 8. 안전 경계

- HTTP 200인 경로는 재시작하지 않는다.
- WSL 배포판 전체를 중지하거나 재시작하지 않는다. keeper와 MeshCentral 유닛만 다룬다.
- Windows MeshCentral과 다른 COM2 서비스·러너를 건드리지 않는다.
- SSH 키·인증·알림 스크립트·스케줄 주기를 바꾸지 않는다.
- 설정된 전달 작업 외의 작업을 중지·시작하지 않는다.
- 실제 장애를 만들지 않고 fixture로 분기를 검증한다.

## 9. 남은 운영 확인

- 배포 후 정상 상태 1회 실행에서 불필요한 재시작 0건, PID·시작 시각 불변.
- watchdog 수동 실행에서 keeper 탐지가 `KEEPALIVE_RUNNING`으로 기록되는지.
- 두 스케줄 작업의 `LastTaskResult=0`.
- 기존 알림 경로(스크립트·알림 채널) 무변경.
