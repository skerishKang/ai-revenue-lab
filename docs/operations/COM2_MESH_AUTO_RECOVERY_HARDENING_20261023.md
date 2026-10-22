# COM2 Mesh 자동 복구 강화 — 재부팅 후 자동 시작 (2026-10-23)

- 구현: `scripts/ops/com2_mesh/` 아래 엔진, 터널 supervisor, 작업 XML 템플릿, 자동 시작 관측 프로브, selftest 3종
- 설정 예시: `scripts/ops/com2_mesh/com2_mesh_config.template.json`
- 관련: `docs/operations/COM2_MESH_AUTO_RECOVERY_20261021.md` (기존 복구 엔진), `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md`
- 상태: **SOURCE_IMPLEMENTED / FIXTURE_SELFTEST_PASSED / OPERATIONAL_APPLY_PENDING**
- 이 작업에서 하지 않은 것: 작업 XML 등록·적용, 프로세스 종료·재시작, 재부팅, failover 전환, 외부 알림 전송, Native·#5574 문맥 파일 변경

## 1. 확인된 결함

| ID | 결함 | 확인된 상태 | 수정 |
|---|---|---|---|
| D1 | 터널 작업의 시간 트리거 반복이 만료됨 | 시간 트리거가 `Interval=PT5M`, `Duration=P1D`로 등록되어 있어 반복이 하루 뒤 끝났다. 2026-10-23 읽기 전용 조회에서 `NextRunTime`이 비어 있었다. 다음 재부팅 전까지 5분 반복은 다시 작동하지 않는다. | 반복에 `Duration`을 두지 않는 작업 XML 템플릿과 렌더·검증 스크립트. 만료된 XML을 거부하는 mutation 테스트. |
| D2 | 래퍼의 SSH 자식 수명과 단일 인스턴스 | 기존 경로는 VBS → `.cmd` 래퍼 → `ssh` 1회 실행이며 재시도 루프가 없다. 래퍼를 강제 종료하면 `ssh.exe`가 남을 수 있고, 두 번째 실행이 같은 포트를 두고 경쟁할 수 있다. 래퍼의 `%ERRORLEVEL%` 기록은 파싱 시점 확장으로 신뢰할 수 없다. | 단일 인스턴스 supervisor: 배타적 파일 잠금, Windows job object(`KILL_ON_JOB_CLOSE`), 제한 재시도, 상태·로그 JSON. 자식이 실제로 포트를 소유했을 때만 forwarding으로 인정한다. |
| D3 | `remote_probe_failed` 원인 미구분, unknown unit 재시작 위험 | 원격 프로브 실패가 하나의 문구로 기록됐다. 기존 계획은 `remote_unit -ne 'active'`였으므로 `unknown`도 unit 재시작으로 이어질 수 있었다. HTTP 000만으로 COM2 unit을 재시작하면 안 된다. | SSH 실패 원인 코드, `com2_state_source=direct|unverified`, unknown keeper/unit는 `record_only`. HTTP 000만으로는 어떤 COM2 서비스 조치도 계획하지 않는다. |
| D4 | `auto_start_verified` 하드코딩 | 운영 health 스크립트가 `$true`를 고정하고 HTML에도 이전 부팅 시험 결과를 고정 표기했다. 2026-10-23 실제 관측에서는 D1 때문에 `false`여야 한다. | 부팅·서비스·작업 트리거·다음 실행·마지막 실행·리스너·HTTP를 15개 체크로 관측하는 read-only 프로브. health 스크립트 연결은 적용 계획에 포함했다. |
| D5 | 알림 재등록 | 이 작업 범위 밖. 알림 스크립트와 알림 채널은 변경하지 않았고 외부 알림을 보내지 않았다. | 별도 항목으로 유지한다. |

## 2. 소스 변경

### 2.1 복구 엔진 — `com2_mesh_recovery.ps1`

- 원격 프로브 실패 원인: `ssh_timeout`, `ssh_connect_timeout`, `ssh_auth_failed`, `ssh_connection_refused`, `ssh_network_unreachable`, `ssh_transport_error`, `probe_script_failed`, `probe_no_verdict`, `ssh_client_missing`, `not_probed`.
- 기록 필드 추가: `remote_cause`, `com2_state_source`, `retry_decision`, `retry_attempt`, `retry_max`, `next_attempt_at`. health log `key=value` 한 줄에도 같은 값을 넣는다.
- `com2_mesh_down` 조치:
  - 원격 프로브가 답하지 않았으면 `record_only`.
  - keeper가 `MISSING`이면 `start_keeper`.
  - unit이 `inactive` 또는 `failed`이면 `restart_mesh_service`.
  - unit/keeper가 `unknown`이면 `record_only`이며 사유에 "직접 관측되지 않음"을 남긴다.
- `remote_probe_failed`는 `record_only`이며 사유에 원인 코드와 원격 오류를 함께 남긴다.
- bounded retry: 아래 §3.1.
- 새 설정 키(기본값): `recovery_max_attempts=3`, `recovery_backoff_schedule_seconds=[300,900,1800]`, `recovery_cooldown_seconds=300`, `recovery_retry_window_seconds=3600`.

### 2.2 터널 supervisor — `com2_mesh_tunnel_supervisor.ps1`

- 하나의 supervisor가 하나의 SSH 자식만 소유한다.
- 잠금: `FileShare.None`으로 연 잠금 파일을 프로세스 수명 동안 유지한다. 중복 실행은 종료 코드 2와 `duplicate_refused` 로그를 남기고 살아 있는 상태를 덮어쓰지 않는다. 잠금은 OS 핸들이므로 비정상 종료 시 자동으로 풀린다.
- 자식 수명: 자식을 job object에 즉시 할당하고 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`를 설정한다. supervisor를 강제 종료해도 자식이 남지 않는다.
- 준비 판정: 설정된 loopback 포트의 리스너 소유 PID가 자식 PID와 같을 때만 forwarding으로 전환한다. 다른 프로세스가 포트를 잡고 있으면 준비 실패로 처리하고 자식을 종료한다.
- 재시도: `tunnel_backoff_schedule_seconds`(기본 5/15/30/60초), `tunnel_max_attempts`(기본 5). `tunnel_stable_seconds`(기본 120초) 이상 유지된 실행은 시도 예산을 초기화한다. 예산 소진 시 종료 코드 3으로 끝나고, 5분 작업 트리거가 새 에피소드를 시작한다.
- 상태: `com2_mesh_tunnel_supervisor/v1` JSON(`state`, `pid`, `child_pid`, `attempt`, `max_attempts`, `stable_runs`, `forwarding_since`, `next_attempt_at`, `last_exit_code`, `last_run_seconds`, `last_error`)과 한 줄 로그.
- COM2 서비스는 건드리지 않는다. 서비스 조치는 기존 복구 엔진만 수행한다.

### 2.3 작업 XML — `com2_mesh_tunnel_task.template.xml`, `com2_mesh_task_template.ps1`

- BootTrigger(30초 지연) + TimeTrigger(`PT5M` 반복, **Duration 없음**).
- `StartWhenAvailable=true`, `MultipleInstancesPolicy=IgnoreNew`, `ExecutionTimeLimit=PT0S`, S4U + HighestAvailable.
- 템플릿에는 계정·경로·키가 없다. 렌더 스크립트가 UTF-16 BOM으로 쓰고 다음을 검증한다: 부팅/시간 트리거, 반복 주기, Duration 부재, StartWhenAvailable, IgnoreNew, 무제한 실행, principal, Exec 경로, 남은 placeholder, XML 유효성.
- 렌더 스크립트는 `Register-ScheduledTask`, `Unregister-ScheduledTask`, `schtasks`를 호출하지 않는다.

### 2.4 자동 시작 관측 — `com2_mesh_autostart.ps1`

15개 체크를 세 상태로 기록한다.

```text
true        관측했고 조건을 만족
false       관측했고 조건을 만족하지 않음
null        관측하지 못함(unverified)
```

`auto_start_verified=true`는 15개가 모두 `true`일 때만이다. `auto_start_state`는 `verified|failed|unverified`이며 `failed_checks`, `unverified_checks`를 함께 남긴다.

체크:

```text
boot_time_observed
mesh_agent_service_automatic
mesh_agent_running
mesh_agent_running_since_boot
tunnel_task_exists
tunnel_task_enabled
tunnel_task_autostart_trigger
tunnel_task_repetition_unbounded
tunnel_task_next_run_present
tunnel_task_ran_after_boot
tunnel_task_last_result_ok
tunnel_listener_present
tunnel_listener_started_after_boot
tunnel_listener_process_matches
mesh_http_200
```

- 조회는 read-only다: 서비스·작업·리스너 조회, loopback HTTP GET 1회. 프로세스·서비스·작업을 시작·중지·변경하지 않는다.
- 기록 스키마: `com2_mesh_autostart/v1`. `-ObservationFile`은 selftest/mock 주입용이며, 이 경우 호스트를 조회하지 않는다.
- 관측 한계: 현재 실행이 부팅 트리거 때문에 시작됐는지, 수동 시작인지는 이 프로브만으로 구분할 수 없다. 부팅 트리거의 존재·비만료 반복·부팅 후 실행·부팅 후 리스너를 각각 기록한다. 인과 증명은 통제된 재부팅 시험이 필요하다.

### 2.5 selftest

| 파일 | 검증 |
|---|---|
| `com2_mesh_recovery_selftest.ps1` | 분기별 분류·계획·코드, 원인별 원격 실패, unknown 상태의 record_only, retry backoff/exhaustion/window 재개/class 전환/healthy 초기화, Simulate가 시도를 소비하지 않음, 상태·로그·락 |
| `com2_mesh_tunnel_supervisor_selftest.ps1` | 중복 supervisor 거부와 살아 있는 상태 보존, 강제 종료 시 자식 회수, 제한 재시도, stable 실행의 예산 초기화, 리스너 미준비, 다른 프로세스가 포트를 소유한 경우 거부, 작업 XML 불변식과 만료 XML 거부 |
| `com2_mesh_autostart_selftest.ps1` | 15개 체크의 true/false/null, 만료 반복, 지난 NextRunTime, 부팅 전 실행, 수동/중지 서비스, 리스너 없음/다른 프로세스/부팅 전 시작, HTTP 500, 부팅 시각 미관측, 조회 실패, verified→failed→verified 전이, CLI JSON 계약 |

## 3. 동작 계약

### 3.1 bounded retry / backoff / cooldown

에피소드 키는 `class|planned_action`이다.

```text
조치 실행 → HTTP 200 실패
  attempt_count += 1
  last_attempt_at = 실패 시각
  next_attempt_at = 실패 시각 + schedule[min(attempt-1)]
schedule = 300 / 900 / 1800초 (마지막 값에서 상한)

다음 관측, 같은 키
  now < next_attempt_at            → skipped_backoff / RECOVERY_BACKOFF (조치 없음)
  now - last_attempt_at < 300초    → cooldown backoff
  attempt_count >= 3이고 최근 시도 후 3600초 미경과
                                    → skipped_exhausted / RECOVERY_RETRY_EXHAUSTED
  최근 시도 후 3600초 경과          → 새 에피소드로 시도 재개

다른 class/action key                → attempt_count=0, 즉시 계획
healthy 또는 조치 후 HTTP 200        → 에피소드 초기화, last_success_at 기록
Simulate / DryRun                   → 시도 횟수를 소비하지 않음
```

### 3.2 `remote_probe_failed`와 COM2 상태

```text
원격 프로브 실패 → record_only, remote_cause와 원격 오류 기록
COM2 SSH TCP 실패 → record_only (com2_ssh_unreachable)
HTTP 000 + 원격 HTTP 000 + keeper/unit unknown → record_only, 직접 관측 아님
HTTP 000 + keeper MISSING(직접 관측) → start_keeper
HTTP 000 + unit inactive/failed(직접 관측) → restart_mesh_service
HTTP 200(원격) + 로컬 HTTP 000 → tunnel_broken → restart_tunnel
loopback 리스너 없음 → tunnel_listener_down → restart_tunnel
```

HTTP 000 하나만으로 COM2 unit을 재시작하지 않는다. `com2_state_source=unverified`인 기록은 COM2가 죽었다는 증거가 아니다.

### 3.3 중복 복구 방지

```text
작업 스케줄러       MultipleInstancesPolicy=IgnoreNew
supervisor          배타적 파일 잠금, 중복이면 exit 2 + duplicate_refused
자식 수명           job object KILL_ON_JOB_CLOSE
준비 판정           리스너 소유 PID == 자식 PID
복구 엔진           lock_file(PID+시작 시각)과 bounded retry
```

서로 다른 계층이 같은 일을 반복하지 않는다. 엔진은 서비스/전달 조치를 계획하고, supervisor는 자기 자식만 관리한다.

## 4. 관측 근거 (2026-10-23, 읽기 전용)

COM1에서 읽기 전용으로 관측한 값:

```text
마지막 부팅                       2026-10-23 00:44:45
Mesh Agent 서비스                 Running, StartMode=Auto
MeshAgent 프로세스 시작           2026-10-23 00:46:34 (부팅 후)
터널 작업 PADIEM-Mesh-Tunnel       Enabled, State=Ready
  트리거                          Boot + Time (Interval=PT5M, Duration=P1D=86400초)
  LastRunTime                     2026-10-23 01:00:00
  LastTaskResult                  0
  NextRunTime                     (비어 있음)
loopback 4443 리스너               있음, 프로세스 시작 2026-10-23 01:00:16 (부팅 후)
MeshCentral HTTP via tunnel       200
자동 시작 관측 판정                auto_start_verified=false
  실패 체크                       tunnel_task_repetition_unbounded
                                  tunnel_task_next_run_present
```

- 반복이 유한 Duration으로 등록되어 만료됐고 `NextRunTime`이 비어 있다. 부팅 트리거는 남아 있지만 5분 반복은 다음 재부팅 전까지 다시 작동하지 않는다.
- 01:00:00 실행이 부팅 트리거에 의한 것인지 수동 시작인지 이 관측만으로 구분할 수 없다. 부팅(00:44:45)과 실행(01:00:00) 사이의 간격이 그대로 남아 있다.
- health 스크립트의 고정 `auto_start_verified=true`와 HTML의 이전 부팅 시험 표기는 이 관측과 모순된다.

## 5. 적용 계획 (이 작업에서 실행하지 않음)

1. 승인된 유지보수 창에서 COM1의 현재 작업 XML, 설정, health 스크립트, 기존 래퍼를 타임스탬프 백업으로 복사한다. 현재 `NextRunTime`과 `LastRunTime`도 기록한다.
2. 이 PR의 파일을 COM1 운영 디렉터리에 배포한다. 설정 파일은 기존 키를 유지하고 새 키를 병합한다. JSON 파싱과 필수 키 존재를 확인한다.
3. 작업 XML을 렌더한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_task_template.ps1 `
  -OutputPath <new-task.xml> `
  -TaskUser <현재 작업 계정> `
  -StartBoundary <적용 시각 기준 로컬 시각> `
  -PowerShellPath <powershell.exe> `
  -SupervisorPath <com2_mesh_tunnel_supervisor.ps1> `
  -ConfigPath <com2-mesh-config.json> `
  -WorkingDirectory <운영 디렉터리>
```

렌더 스크립트의 `violations=[]`와 종료 코드 0을 확인한다. 렌더만으로는 작업이 바뀌지 않는다.

4. 승인된 적용 단계에서만 같은 이름 `PADIEM-Mesh-Tunnel`로 작업을 등록·갱신한다. 기존 작업을 삭제하지 않고 `Register-ScheduledTask -Force`로 교체하거나, 백업 XML로 즉시 되돌릴 수 있는 상태를 유지한다.
5. health 스크립트의 고정값을 관측값으로 교체한다.

```powershell
$autostartProbe = Join-Path $base "com2_mesh_autostart.ps1"
$autostart = $null
if (Test-Path -LiteralPath $autostartProbe) {
    $raw = & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $autostartProbe `
        -Config $configPath -Json 2>$null
    $line = @($raw) | Where-Object { ([string]$_).Trim().StartsWith('{') } | Select-Object -Last 1
    if ($line) { try { $autostart = $line | ConvertFrom-Json } catch { $autostart = $null } }
}
$status.auto_start_verified = if ($autostart) { [bool]$autostart.auto_start_verified } else { $false }
$status.auto_start_state = if ($autostart) { [string]$autostart.auto_start_state } else { "unverified" }
$status.auto_start_failed_checks = if ($autostart) { (@($autostart.failed_checks) -join ",") } else { "probe_missing" }
$status.auto_start_unverified_checks = if ($autostart) { (@($autostart.unverified_checks) -join ",") } else { "probe_missing" }
$status.auto_start_probe_ts = if ($autostart) { [string]$autostart.ts } else { "" }
```

HTML의 고정 문구도 `auto_start_state`, `auto_start_failed_checks`, `auto_start_unverified_checks`를 표시하도록 바꾼다. `true`/`false`의 색상 클래스는 상태에서 계산한다.

6. 적용 직후 확인(모두 읽기 전용):
   - `Get-ScheduledTaskInfo`: `NextRunTime`이 비어 있지 않고, 두 번의 5분 주기 뒤 `LastRunTime`이 전진한다.
   - `com2_mesh_autostart.ps1`: `auto_start_state=verified`이고 실패/unverified 체크가 0이다.
   - `com2_mesh_recovery.ps1 -DryRun`: `healthy`, `planned_action=none`.
   - 리스너 소유 프로세스가 하나이고 supervisor 상태의 `child_pid`와 일치한다.
   - 두 번째 supervisor 실행은 exit 2와 `duplicate_refused`를 남기고 기존 상태를 바꾸지 않는다(승인된 창에서만 실행).

## 6. 롤백 계획

1. 승인된 창에서 작업을 중지하고 새 작업을 해제한다. 백업 XML을 같은 이름으로 다시 등록한다.
2. health 스크립트, 설정, 기존 래퍼를 타임스탬프 백업에서 복원한다.
3. supervisor의 잠금·상태·로그 파일은 새 작업이 해제된 뒤 정리한다. 실행 중인 자식이 있으면 task 종료와 job object가 함께 회수한다.
4. 백업 XML에는 만료된 `P1D` 반복이 들어 있다. 그대로 복원하면 5분 반복은 다시 만료 상태가 된다. 롤백 시 다음 중 하나를 명시적으로 선택한다.
   - 백업 XML의 반복 `Duration`만 제거해 재등록한다(트리거 수정, 조치 경로는 기존 래퍼).
   - 또는 다음 재부팅 전까지 수동 시작 절차를 유지한다.
5. 확인: 작업 Enabled/Ready, 리스너 1개, HTTP 200, `NextRunTime` 존재, 중복 프로세스 없음.

## 7. 검증 계획과 현재 증거

- fixture selftest: 복구 엔진, supervisor, 자동 시작 프로브. 2026-10-23 로컬 실행 결과는 §4와 별도로 실행 로그에 남긴다.
- mock 장애 주입: 만료 반복, 리스너 없음, 다른 프로세스의 포트 점유, HTTP 000/500, 원격 SSH 원인별 실패, retry backoff/cooldown/exhaustion/window 재개, 중복 supervisor.
- 상태 전이: verified → failed → verified, first_fault 보존/자기 회복, retry 에피소드 초기화.
- 읽기 전용 사전 관측: §4. 적용 전 상태를 `auto_start_verified=false`로 기록했다.
- 적용 후: §5.6. 이 작업에서는 실행하지 않았다.
- 미검증: 부팅 트리거가 실제로 재부팅 직후 작업을 시작하는지의 인과. 통제된 재부팅 시험 전까지는 "부팅 후 실행이 관측됨"과 "부팅 트리거가 실행했다"를 구분한다.
- 미검증: COM2 unit/keeper의 실제 장애 주입. 이 작업은 fixture로만 분기를 검증했고 COM2 서비스를 건드리지 않았다.

## 8. 비범위와 남은 항목

- Native 등록·트레이·연결 UI와 #5574 문맥 도구 선택 파일은 변경하지 않았다.
- 알림 재등록과 알림 채널은 별도 항목이다. 이 작업에서 외부 알림을 보내지 않았다.
- Oracle failover controller와 claim fence 동작은 변경하지 않았다.
- 운영 작업 XML 적용, 프로세스 종료·재시작, 재부팅, 실제 failover 전환은 하지 않았다.
- 적용 후 남은 운영 확인:
  - 통제된 재부팅 1회에서 작업이 30초 지연 부팅 트리거로 시작하고 리스너가 부팅 후 생성되는지.
  - 5분 반복이 24시간 이상 유지되는지(`NextRunTime` 전진).
  - supervisor 중복 실행이 exit 2로 끝나고 자식이 하나만 남는지.
  - health 상태의 `auto_start_verified`가 관측값과 일치하는지.
  - 알림 재등록 여부.
