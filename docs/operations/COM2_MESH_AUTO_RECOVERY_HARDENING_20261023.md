# COM2 Mesh 자동 복구 강화 — 재부팅 후 자동 시작 (2026-10-23)

## 2026-10-23 operational transition

- Read-only observation at 20:58 KST: the running COM1 Mesh Agent process has an established direct TCP connection to `192.168.0.101:4443`.
- `PADIEM-Mesh-Tunnel` has `Settings.Enabled=false`. Its reported task state was still `Running`; disabled scheduling does not establish that an existing task or supervisor has stopped or been removed.
- The sections below retain the #5578 source/recovery design and its earlier evidence; they do not imply that the legacy tunnel is the current COM1 connection path.
- Removal of the obsolete tunnel task/supervisor and review of the #5578 layers are deferred until 2026-10-25 or later and tracked in #5643.
- This note records observed state only. No task, service, runtime setting, restart or reboot was changed to produce it.

- 구현: `scripts/ops/com2_mesh/` 아래 엔진, 터널 supervisor, 작업 XML 템플릿, 자동 시작 관측 프로브, selftest 3종
- 설정 예시: `scripts/ops/com2_mesh/com2_mesh_config.template.json`
- 관련: `docs/operations/COM2_MESH_AUTO_RECOVERY_20261021.md` (기존 복구 엔진), `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md`
- 상태: **SOURCE_IMPLEMENTED / FIXTURE_SELFTEST_PASSED / FINAL_REVIEW_CONDITIONALLY_READY / OPERATIONAL_APPLY_PENDING**
- 통합 기준 PR: #5578. 중복 PR #5577(f1fe620d)은 2026-10-23 통합 링크와 사유를 남기고 superseded로 종료했다. 그 PR의 판정 시계·pending·record-only 누수 수정만 이 PR로 옮겼고, VBS/CMD 실행기와 `lock.d` 잠금 체계는 옮기지 않았다. §9 참조.
- 이 작업에서 하지 않은 것: 병합, 작업 XML 등록·적용, 프로세스 종료·재시작, 재부팅, failover 전환, 외부 알림 전송, Native·#5574 문맥 파일 변경

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
- record-only 사유는 원격 HTTP 값의 성질을 구분한다: `remote_http_reason=remote_probe_failed|remote_http_code|remote_http_no_response`. `000`은 "응답 없음"이며 장애 원인의 증거가 아니다.
- 기록 필드 추가(판정 시계·pending): `recovery_state`, `class_started_at`, `class_age_sec`, `engine_elapsed_sec`, `action_started_at`, `action_finished_at`, `verify_window_sec`, `http200_observed_at`, `http200_first_observed_sec`, `http200_observed_basis`, `pending_since`, `pending_action`, `pending_deadline`, `pending_invalidation`, `max_pending_seconds`, `remote_http_reason`.
- bounded retry: 아래 §3.1. pending 검증 창: 아래 §3.4. 두 시계: 아래 §3.5.
- 새 설정 키(기본값): `recovery_max_attempts=3`, `recovery_backoff_schedule_seconds=[300,900,1800]`, `recovery_cooldown_seconds=300`, `recovery_retry_window_seconds=3600`, `max_pending_seconds=900`.

### 2.2 터널 supervisor — `com2_mesh_tunnel_supervisor.ps1`

- 하나의 supervisor가 하나의 SSH 자식만 소유한다.
- 잠금: `FileShare.None`으로 연 잠금 파일을 프로세스 수명 동안 유지한다. 중복 실행은 종료 코드 2와 `duplicate_refused` 로그를 남기고 살아 있는 상태를 덮어쓰지 않는다. 잠금은 OS 핸들이므로 비정상 종료 시 자동으로 풀린다.
- 자식 수명: 자식을 job object에 할당한 뒤에만 기동으로 인정한다. job object 생성·할당 실패는 치명적으로 처리하고 상태·로그에 남긴다. supervisor가 정상 종료할 때는 자식을 직접 종료한다.
- 준비 판정: 설정된 loopback 포트의 리스너 소유 PID가 자식 PID와 같을 때만 forwarding으로 전환한다. 연결 테이블 조회가 실패하면 `netstat -ano`의 소유 PID로 대조하며, TCP 연결 성공만으로 인정하지 않는다. 다른 프로세스가 포트를 잡고 있으면 준비 실패로 처리하고 자식을 종료한다.
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
| `com2_mesh_recovery_selftest.ps1` | 분기별 분류·계획·코드, 원인별 원격 실패, unknown 상태의 record_only, retry backoff/exhaustion/window 재개/class 전환/healthy 초기화, pending 활성 억제·만료 시 1회 소비와 backoff·만료 예산 소진·pending 중 200 관측·class/조치 변경·비조치 class에서 pending 폐기, record-only pending 누수 없음, 두 시계(에피소드/class) 분리, 관측 200 비소급, Simulate가 시도를 소비하지 않음, 상태·로그·락 |
| `com2_mesh_tunnel_supervisor_selftest.ps1` | 중복 supervisor 거부와 살아 있는 상태 보존, 강제 종료 시 자식 회수, job object 미생성·미할당 시 자식 미기동과 실패 코드, job 닫기 시 소유 자식 회수, 리스너 소유 PID의 cmdlet·netstat 대조, 제한 재시도, stable 실행의 예산 초기화, 리스너 미준비, 다른 프로세스가 포트를 소유한 경우 거부, 작업 XML 불변식과 만료 XML 거부 |
| `com2_mesh_autostart_selftest.ps1` | 15개 체크의 true/false/null, 만료 반복, 지난 NextRunTime, 부팅 전 실행, 수동/중지 서비스, 리스너 없음/다른 프로세스/부팅 전 시작, HTTP 500, 부팅 시각 미관측, 조회 실패, verified→failed→verified 전이, CLI JSON 계약 |

## 3. 동작 계약

### 3.1 bounded retry / backoff / cooldown

에피소드 키는 `class|planned_action`이다.

```text
조치 실행 → 검증 창 안에 HTTP 200 미관측 → pending (§3.4)
pending 만료 → attempt_count += 1
  last_attempt_at = pending_deadline
  next_attempt_at = pending_deadline + schedule[min(attempt-1)]
schedule = 300 / 900 / 1800초 (마지막 값에서 상한)

다음 관측, 같은 키
  pending 활성                     → RECOVERY_PENDING_AWAITING_VERIFY (조치 없음, 시도 미소비)
  now < next_attempt_at            → skipped_backoff / RECOVERY_BACKOFF (조치 없음)
  now - last_attempt_at < 300초    → cooldown backoff
  attempt_count >= 3이고 최근 시도 후 3600초 미경과
                                    → skipped_exhausted / RECOVERY_RETRY_EXHAUSTED
  최근 시도 후 3600초 경과          → 새 에피소드로 시도 재개

다른 class/action key                → attempt_count=0, 즉시 계획
healthy 또는 pending 중 HTTP 200     → 에피소드 초기화, last_success_at 기록
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

### 3.4 pending 검증 창

`verify_timeout_seconds`(기본 30초) 안에 HTTP 200을 관측하지 못한 조치는 실패가 아니라 **pending**이다. MeshCentral 기동이나 SSH 채널 재수립은 30초보다 오래 걸릴 수 있으므로, 검증 창 실패를 즉시 실패로 확정하면 정상 복구를 중복 재시작으로 방해한다.

```text
조치 실행 완료 → 검증 창 안 HTTP 200 없음
  pending_since = 조치 완료 시각
  pending_action = 실행한 조치
  pending_deadline = 조치 완료 시각 + max_pending_seconds(900)
  recovery_ok=pending, recovery_state=pending, code=RECOVERY_PENDING_HTTP_<code>
  attempt_count는 소비하지 않음

다음 관측, 같은 class·같은 조치
  now < pending_deadline   → RECOVERY_PENDING_AWAITING_VERIFY, 새 조치 없음
  now >= pending_deadline  → pending 만료: 시도 1회 소비, backoff 진입
                             code=RECOVERY_FAILED_PENDING_EXPIRED,
                             pending_invalidation=pending_expired
  HTTP 200 관측            → RECOVERED_HTTP200_OBSERVED_AFTER_PENDING
                             pending_since를 관측 시각으로 기록하고 에피소드 초기화

pending 무효화 (다음 중 하나)
  class 변경               → pending_invalidation=class_changed
  같은 class, 조치 불가    → pending_invalidation=class_not_actionable
  같은 class, 다른 조치    → pending_invalidation=action_changed
```

- pending은 성공이 아니다. `recovery_ok=pending`으로 기록하며 `recovery_at`을 채우지 않는다.
- pending 활성 중에는 새 조치를 계획하지 않는다. 5분 주기 검사가 pending을 관측해도 `RECOVERY_PENDING_AWAITING_VERIFY`만 남는다.
- `max_pending_seconds=900`은 5분 watchdog 주기보다 길어야 한다. 그렇지 않으면 느린 복구를 관측하기 전에 창이 닫힌다.
- HTTP 200을 나중에 관측하면 `http200_observed_at`은 **관측 시각**이다. `http200_first_observed_sec`는 `pending_since`에서 관측 시각까지의 거리이며, 복구가 그 사이 어느 시점에 일어났다는 상한을 뜻한다. 복구 시각을 과거로 소급하지 않는다.
- record-only 분기로 class가 바뀌거나 조치가 없어지면 pending을 즉시 닫는다. 닫지 않으면 이후 무관한 조치를 억제하거나 거짓 실패로 만료된다.
- Simulate/DryRun은 조치를 실행하지 않으므로 pending을 만들지 않는다.

### 3.5 두 장애 시계

| 필드 | 의미 |
|---|---|
| `first_fault` | 현재 장애 에피소드의 최초 감지 시각. healthy가 될 때까지 보존한다. |
| `fault_age_sec` | 에피소드 전체 경과. class가 바뀌어도 줄지 않는다. |
| `class_started_at` | 현재 class가 시작된 시각. class가 바뀌면 재설정한다. |
| `class_age_sec` | 현재 class의 경과. 새 class의 진행 속도를 에피소드 전체와 분리해 보여준다. |

예: `remote_probe_failed`가 1시간 지속되다 `tunnel_broken`으로 바뀌면 `fault_age_sec`는 1시간 이상, `class_age_sec`는 수 초가 된다.

### 3.6 기존 소비자 호환성

운영 health/alert 스크립트는 저장소 밖 COM1에 있으며, 2026-10-23 읽기 전용으로 확인했다.

| 소비자 | 읽는 필드 | 영향 |
|---|---|---|
| `com2-mesh-health.ps1` | `ts`, `com2_ssh`, `tunnel_tcp`, `mesh_http`, `class`, `remote_ok`, `remote_keeper`, `remote_unit`, `planned_action`, `action`, `executed`, `recovery_ok`, `code`, `recovery_at`, `first_fault`, `fault_age_sec`, `elapsed_sec`, `error`, `detail`, `remote_http` | 변경 없음. 새 필드는 무시한다. `recovery_ok=pending`은 `yes`/`no`가 아니므로 HTML에서 중립색으로 표시되고 성공으로 오인되지 않는다. |
| `com2-mesh-alert.ps1` | `timestamp`, `com2_ssh_tcp`, `com1_tunnel_tcp_4443`, `meshcentral_http_via_tunnel`, `error_reason` | 변경 없음. 복구 필드를 읽지 않는다. 엔진 필드 이름 변경·삭제 없음. |

호환 규칙: 기존 필드 이름과 의미를 바꾸지 않고 필드만 추가한다. `action`에 `skipped_backoff`/`skipped_exhausted`/`skipped_locked`, `recovery_ok`에 `pending`, `code`에 새 값이 추가되지만 소비자는 문자열로 다룬다.

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

## 5. 운영 적용 계획 (실행 가능한 순서, 이 작업에서 실행하지 않음)

전제: COM1 관리자 권한과 승인된 유지보수 창이 필요하다. 9개 단계 각각에 정상 판정과 실패 시 롤백 지점(§6)이 있다. 이번 작업에서는 어느 단계도 실행하지 않았다.

### 5.1 사전 확인 (읽기 전용)

| # | 확인 | 정상 판정 | 실패 시 |
|---|---|---|---|
| 5.1.1 | 작업 `PADIEM-Mesh-Tunnel` | `Get-ScheduledTask`와 `Get-ScheduledTaskInfo`가 조회되고 Enabled/Ready 또는 Running | 조회 불가면 창을 열지 않는다 |
| 5.1.2 | loopback 4443 리스너 | 소유 PID 1개, 설정된 전달 프로세스(`ssh.exe`), 시작 시각과 부모 체인 기록 | 소유자 불명이면 창을 열지 않는다 |
| 5.1.3 | Mesh Agent | Running, StartMode=Auto | 창을 열지 않는다 |
| 5.1.4 | loopback HTTP | 200 | 200이 아니면 기존 장애를 먼저 조사하고 창을 연기한다 |
| 5.1.5 | 진행 중 PC 작업 | MeshAgent PID의 자식 프로세스에 실행 중인 cmd/powershell 등이 없고, `com2_mesh_recovery.ps1 -DryRun`이 `healthy`, health 로그에 `pending` 없음 | 진행 중 작업이 끝날 때까지 기다린다. 강제 종료하지 않는다 |
| 5.1.6 | 감시자 식별 | health/recovery를 주기 실행하는 작업·프로세스를 식별하고 창 동안 비활성화할 목록 기록 | 식별 실패 시 창 동안 수동 관측으로 대체하고 기록한다 |
| 5.1.7 | 디스크·경로 | 백업·XML·상태 파일을 쓸 경로에 여유 | 창을 열지 않는다 |

5.1.5가 이 창의 유일한 진행 작업 보존 장치다. 기존 체인은 전달 계층만 교체하므로, 명령 실행 중 전송을 끊으면 진행 중 작업의 결과 전달을 보장할 수 없다. 창 시작 전에 실행 중 작업이 없어야 한다.

### 5.2 백업과 SHA256 manifest

```powershell
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $opsRoot ("backup-" + $ts)
New-Item -ItemType Directory -Path $backup | Out-Null
Export-ScheduledTask -TaskName 'PADIEM-Mesh-Tunnel' |
    Set-Content -LiteralPath (Join-Path $backup 'PADIEM-Mesh-Tunnel.xml') -Encoding Unicode
$files = @('background-tunnel.vbs', 'padiem-tunnel-wrapper.cmd', 'padiem-tunnel.cmd',
    'com2-mesh-config.json', 'com2-mesh-health.ps1', 'com2-mesh-alert.ps1',
    'com2-mesh-recovery-state.json', 'com2-mesh-status.json')
foreach ($f in $files) {
    $src = Join-Path $opsRoot $f
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination (Join-Path $backup $f) }
}
Get-ChildItem -LiteralPath $backup -File | Get-FileHash -Algorithm SHA256 |
    Select-Object Path, Hash | ConvertTo-Json -Depth 3 |
    Set-Content -LiteralPath (Join-Path $backup 'backup-manifest.json') -Encoding UTF8
```

- 함께 기록: `LastRunTime`, `LastTaskResult`, `NextRunTime`, 작업 Principal(UserId/RunLevel/LogonType), 리스너 PID·시작 시각·부모 PID, MeshAgent PID.
- 기존 실행기 파일은 복사만 하고 이동·삭제하지 않는다. 적용 창에서도 그대로 두어 롤백 시 파일 복원 없이 되돌릴 수 있게 한다.
- 정상 판정: manifest에 백업 파일 수만큼 항목이 있고 모든 해시가 채워져 있다. 실패 시 아직 아무것도 바뀌지 않았으므로 중단한다(R1).

### 5.3 배포 준비 (아직 작업 정의는 바꾸지 않음)

1. 운영 디렉터리에 복사: `com2_mesh_tunnel_supervisor.ps1`, `com2_mesh_autostart.ps1`, `com2_mesh_task_template.ps1`, `com2_mesh_tunnel_task.template.xml`, 갱신된 `com2_mesh_recovery.ps1`. 덮어쓰는 파일은 5.2 백업에 원본이 있다.
2. 설정 병합: 기존 키 값은 유지하고 새 키만 추가한다. `tunnel_lock_file`, `tunnel_state_file`, `tunnel_log`, `tunnel_ssh_path`, `tunnel_stable_seconds`, `tunnel_backoff_schedule_seconds`, `tunnel_max_attempts`, `tunnel_ready_wait_seconds`, `tunnel_require_listener`, `recovery_max_attempts`, `recovery_backoff_schedule_seconds`, `recovery_cooldown_seconds`, `recovery_retry_window_seconds`, `max_pending_seconds`.
   - `tunnel_ssh_path`는 기본값(`%SystemRoot%\System32\OpenSSH\ssh.exe`)을 그대로 쓰지 않는다. 5.1.2에서 기록한 **기존 체인이 실제로 사용한 ssh 실행 파일 경로**로 명시한다. 두 ssh 구현은 known_hosts·키 해석·에이전트 동작이 다르므로 기본값 교체는 전환 실패 원인이 된다.
   - `ConvertFrom-Json`과 필수 키 존재를 확인한다. supervisor는 필수 키 누락 시 시작 단계에서 예외로 끝나므로, 창 전에 파싱을 통과해야 한다.
3. XML 렌더(작업 정의는 아직 변경되지 않는다):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_task_template.ps1 `
  -OutputPath <new-task.xml> `
  -TaskUser <5.2에서 기록한 현재 작업 계정> `
  -StartBoundary <창 시작 로컬 시각> `
  -PowerShellPath <powershell.exe> `
  -SupervisorPath <운영 디렉터리의 com2_mesh_tunnel_supervisor.ps1> `
  -ConfigPath <운영 디렉터리의 com2-mesh-config.json> `
  -WorkingDirectory <운영 디렉터리>
```

4. 정상 판정: 렌더 종료 코드 0, `ok=true`, `violations=[]`. 배포된 파일의 SHA256을 새 manifest에 기록해 저장소 사본과 같음을 확인한다. 실패 시 R1.

### 5.4 기존 SSH 체인 종료 (순서 고정)

1. `Disable-ScheduledTask -TaskName 'PADIEM-Mesh-Tunnel'`. 트리거가 체인을 다시 시작하지 못하게 한다. `Get-ScheduledTask`로 Disabled를 확인한다.
2. 리스너 PID L과 시작 시각을 다시 기록하고, 프로세스 이름과 부모 체인이 기존 래퍼 계열인지 확인한다. 다르면 여기서 멈추고 조사한다.
3. `Stop-ScheduledTask -TaskName 'PADIEM-Mesh-Tunnel'`.
4. 10초 기다린 뒤 L이 살아 있으면 `Stop-Process -Id L -Force`. 기존 체인에는 job object가 없어 래퍼 종료만으로는 ssh 자식이 남을 수 있다. 포트 4443에 `-L` 전달을 가진 ssh 프로세스가 남지 않았는지 확인한다.
5. 래퍼 프로세스가 없음을 확인한 뒤 `padiem-tunnel.lock.d`가 남아 있으면 제거하고 존재 여부를 기록한다. 이 디렉터리가 남으면 롤백 시 기존 래퍼가 즉시 rc=3으로 끝난다(§6).
6. `Get-NetTCPConnection -State Listen -LocalPort 4443`이 30초 동안 비어 있는지 확인한다. 다른 프로세스가 포트를 잡고 있으면 supervisor를 시작하지 않고 조사한다.

정상 판정: 리스너 없음, ssh 자식 없음, lock.d 없음. 실패 시 R2 또는 R3.

### 5.5 새 작업 등록·기동·검증

1. 5.3의 XML로 `Register-ScheduledTask -TaskName 'PADIEM-Mesh-Tunnel' -Xml (Get-Content -Raw -Encoding Unicode <new-task.xml>) -Force`. 기존 정의는 백업 XML에 있다.
2. 등록 직후 읽기 전용 불변식 확인: BootTrigger + TimeTrigger(`PT5M`, Duration 없음), IgnoreNew, StartWhenAvailable, `PT0S`, Principal이 5.2 기록과 동일, Exec 인자가 supervisor와 실제 설정 경로를 가리킴, 작업 조회 권한 유지.
3. `Start-ScheduledTask`. 60초 안에 다음을 모두 확인한다.
   - 작업 State=Running, supervisor 프로세스 1개.
   - 로그에 `supervisor_start ... job_object=True`, 상태 JSON `state=forwarding`, `child_pid` 존재.
   - 리스너 소유 PID == `child_pid` (`Get-NetTCPConnection` 직접 조회. TCP 연결 성공만으로 판정하지 않는다 — §10 F2).
   - loopback HTTP 200.
4. 중복 게이트(창에서만): supervisor를 한 번 더 직접 실행해 종료 코드 2와 `duplicate_refused` 로그를 확인하고, 살아 있는 상태 JSON의 `child_pid`·`forwarding_since`가 바뀌지 않았는지 비교한다.

정상 판정: 2~4가 모두 참. 실패 시 R4.

### 5.6 job object 자식 회수 게이트 (창 안에서 1회, 파괴적)

job object 생성·할당 실패는 이제 치명적으로 끝나고 상태·로그에 남는다. 이 게이트는 정상 기동 후 `KILL_ON_JOB_CLOSE`가 실제로 자식을 회수하는지 확인하는 런타임 확인이다.

1. supervisor PID S, 자식 PID C, 포트 소유자가 C임을 기록한다.
2. `Stop-Process -Id S -Force` (작업이 아니라 supervisor 프로세스).
3. 10초 안에 C가 사라지고 포트 4443이 비는지 확인한다. C가 살아 있으면 job object가 런타임에 적용되지 않은 것이므로 R4로 롤백하고 §10 F1을 실제 결함으로 승격한다.
4. `Start-ScheduledTask`로 다시 기동하고 5.5.3의 검증을 새 S/C로 반복한다.

### 5.7 10분 관찰 (5분 주기 2회)

매분 읽기 전용으로 확인한다.

- `Get-ScheduledTaskInfo`: `NextRunTime`이 5분씩 전진하고 미래다. `LastTaskResult=267009`(실행 중)인 동안 `LastRunTime`은 전진하지 않는다. supervisor가 계속 실행 중이면 IgnoreNew가 새 인스턴스를 막기 때문이며 정상이다. 구 계획의 "두 주기 뒤 `LastRunTime` 전진" 기준은 장기 실행 supervisor에서 성립하지 않으므로 폐기한다.
- 작업 State=Running, supervisor 프로세스 1개, 리스너 1개, 소유 PID == 상태 JSON `child_pid`, HTTP 200.
- 상태 JSON이 `forwarding`을 유지하고 `attempt`가 증가하지 않으며 로그에 `retry_exhausted`가 없다.
- `com2_mesh_autostart.ps1`: `auto_start_state`와 실패/unverified 체크를 기록한다. unverified가 있으면 어느 체크가 왜 관측되지 않았는지 남긴다.
- `com2_mesh_recovery.ps1 -DryRun`: `healthy`, `planned_action=none`.

정상 판정: 이탈 없음, 중복 없음, backoff 증가 없음. backoff 안에서 스스로 회복한 일시 이탈은 기록하되 창 실패로 확정하지 않는다. 재시도 소진 또는 반복 이탈은 R5.

### 5.8 health 스크립트 연결

1. health 스크립트의 고정 `auto_start_verified`를 관측값으로 교체한다.

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

2. HTML의 고정 문구도 `auto_start_state`, `auto_start_failed_checks`, `auto_start_unverified_checks`를 표시하도록 바꾸고 색상 클래스는 상태에서 계산한다.
3. 정상 판정: health 1회 실행 결과에 `auto_start_probe_ts`가 채워지고 `probe_missing`이 없다. 실패 시 R5에서 health 스크립트를 백업으로 복원한다.

### 5.9 마무리·기록

- `apply-record-<ts>.json` 작성: 창 시작·종료, 5.2 manifest 경로와 해시, 렌더 XML 해시, 등록된 Principal, 5.5/5.6/5.7의 관측값, 판정.
- 백업 디렉터리는 통제된 재부팅 시험이 통과할 때까지 보존한다.
- 기존 실행기 파일은 이 창에서 삭제하지 않는다. 롤백 경로 그 자체다.
- 통제된 재부팅 시험은 별도 승인 작업이다. 5.5의 수동 시작은 전달 기능만 증명하며, 부팅 트리거의 인과는 증명하지 않는다.

## 6. 롤백 계획

공통 순서: 새 작업 중지 → supervisor·자식·리스너가 모두 사라졌는지 확인 → 새 잠금/상태 파일 정리(프로세스 종료 후에만) → 백업 XML 재등록 → lock.d 정리 → 기존 작업 시작 → 리스너·HTTP 확인 → 파일 복원과 해시 확인. 백업 디렉터리는 삭제하지 않는다.

| 지점 | 트리거 | 조치 | 검증 |
|---|---|---|---|
| R1 | 5.2·5.3 실패(아직 작업 정의·실행 체인 무변경) | 덮어쓴 파일만 백업에서 복원, 새로 복사한 파일 제거 | manifest 해시 일치, 작업·리스너 무변경 |
| R2 | 5.4.1~3 후(기존 체인 중지 전후), supervisor 시작 전 | `Enable-ScheduledTask` 후 `Start-ScheduledTask`; 래퍼 생존 확인 후 lock.d 제거 | 리스너 1개, HTTP 200 |
| R3 | 5.4 완료 후, 새 작업 등록 전 | 백업 XML 재등록. `P1D` 만료 반복은 그대로 두지 않고 다음 중 하나를 명시적으로 선택: Duration만 제거해 재등록하거나, 재부팅 전까지 수동 시작 유지 | 작업 Enabled/Ready, 리스너 1개, HTTP 200, `NextRunTime` 존재 또는 수동 절차 기록 |
| R4 | 5.5·5.6 실패 | `Stop-ScheduledTask` → supervisor·자식 확인(자식 생존 시 PID로 종료) → 잠금/상태 파일 정리 → 작업 해제 → 백업 XML 재등록(R3의 Duration 선택 적용) → 시작 | R3와 동일, 중복 프로세스 없음 |
| R5 | 5.7·5.8 실패 | R4 전체 + health 스크립트를 백업으로 복원 | R4 검증 + health가 이전 고정값으로 복귀 |

- R2~R5에서 `padiem-tunnel.lock.d`가 남아 있으면 기존 래퍼가 rc=3으로 즉시 끝난다. 래퍼 프로세스가 없음을 확인한 뒤 제거한다.
- 백업 XML을 그대로 등록하면 5분 반복이 이미 만료된 `P1D` 상태로 돌아간다. 롤백 기록에 어느 선택을 했는지 남긴다.
- 두 체인을 동시에 활성으로 두지 않는다. 기존 체인 복원이 불가능하면 새 작업을 비활성으로 두고 수동 시작 절차를 기록한다.

## 7. 검증 계획과 현재 증거

기준: PR #5578, 코드 HEAD `a80d523e1b8e1f3770e25f11aea4ada871c39e71`, base `3359612e`, 확인 시점 main `94e3c1efd6ecde568c509eee6778d738f6ae0914`.

- 로컬 fixture selftest(Windows PowerShell 5.1): 복구 엔진 `PASS=2475 FAIL=0`, supervisor `PASS=54 FAIL=0`, 자동 시작 프로브 `PASS=97 FAIL=0`. 세 수치는 같은 HEAD에서 실행한 로컬 결과이며 CI 실행이 아니고, PR별 수치를 합산한 값도 아니다.
- 정확한 HEAD CI: `COM2 full policy` success(2026-10-22T16:56:53Z, PR head `a80d523e`). 이 상태는 신뢰된 default-branch sandbox가 PR head를 checkout한 뒤 `git rev-parse HEAD`가 대상 SHA와 같은지 확인하고 게시한다. workflow run 자체의 `head_sha`는 main이므로 run head와 PR head를 같은 값으로 읽지 않는다.
- 그 밖 체크: pass 6(`Cloudflare Pages`, `GitGuardian`, `plan`, `Pull request contract report`, `COM2 policy dispatch`, `COM2 full policy`), skipped 17(경로 필터), failed/pending 0. skipped는 pass가 아니다.
- main 드리프트: 확인 시점 main은 #5576 병합분만 앞서 있고 `scripts/ops/com2_mesh`와 이 문서에 겹치지 않는다. PR은 `MERGEABLE`/`CLEAN`이었다. 저장소에 branch protection이 없어(required status checks API 404) "필수 CI"는 저장소 정책 게이트를 뜻하며 GitHub required check 강제가 아니다.
- mock·상태 전이로 증명한 것: 만료 반복 XML 거부, 리스너 없음/다른 프로세스의 포트 점유, 중복 supervisor exit 2와 상태 보존, 강제 종료 시 자식 회수(mock), 제한 재시도와 stable 예산 초기화, retry backoff/cooldown/exhaustion/window 재개, pending 활성 억제·만료·폐기, record-only pending 누수 없음, 두 시계 분리와 200 비소급, verified→failed→verified.
- 이 문서 커밋은 새 HEAD를 만들므로 그 HEAD의 `COM2 full policy` 상태를 PR #5578 코멘트에 기록한다.
- 미검증(Task Scheduler 실제 동작): 작업 등록·교체·시작, BootTrigger가 재부팅 직후 실제로 시작하는지의 인과, IgnoreNew가 장기 실행 supervisor에서 새 인스턴스를 실제로 막는지, 24시간 반복 유지(`NextRunTime` 전진), job object의 런타임 자식 회수, 기존 체인 중지 시 ssh 자식 잔존 여부.
- 미검증(환경): health 스크립트 연결 후 실제 HTML 표시, COM2 unit/keeper 실제 장애 주입(fixture로만 검증), COM1 재부팅 1회.

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

## 9. PR 통합 근거 (#5578 / #5577)

두 PR은 같은 base(`3359612e`)에서 같은 장애를 다뤘다. 통합 기준은 **#5578**이다. 이유: 단일 supervisor 잠금·자식 소유권(job object)·만료 없는 반복 XML·자동 시작 관측·bounded retry를 이미 포함하고, #5577의 실행기 계층을 합치면 두 번째 잠금/실행 체계가 생긴다.

| 영역 | #5578 (통합 기준) | #5577 (f1fe620d) | 처리 |
|---|---|---|---|
| VBS/CMD/SSH 수명·종료 코드 | 해당 없음(실행 계층 없음) | `background-tunnel.vbs` + `padiem-tunnel-wrapper.cmd` + `padiem-tunnel.cmd` | 옮기지 않음. supervisor의 단일 자식·job object·종료 코드 0/1/2/3이 대신한다. |
| 단일 인스턴스·stale lock·자식 소유권 | `FileShare.None` 잠금 + job object + 리스너 PID 소유권 | `padiem-tunnel.lock.d` 디렉터리 잠금 | 옮기지 않음. 두 잠금 체계를 유지하지 않는다. |
| 작업 XML 반복·자동 시작 검증 | Duration 없는 반복 템플릿·렌더 검증·15개 read-only 체크 | 없음 | #5578 유지 |
| pending 검증 창 | 없음 | `pending_since/action/deadline`, `max_pending_seconds`, record-only 폐기, 테스트 | **이식 완료** (§3.4) |
| retry/backoff/cooldown | `recovery_max_attempts`, schedule, cooldown, retry window | 없음 | #5578 유지, pending 만료가 시도 1회를 소비하도록 결합 |
| 장애 시계·상태 필드 | `first_fault`/`fault_age_sec` | `class_started_at`/`class_age_sec`, `http200_observed_at` 비소급 | **이식 완료** (§3.5) |
| 기존 소비자 호환 | 필드 추가만 | 필드 추가만 | §3.6에서 함께 확인 |

이식하지 않은 파일: `background-tunnel.vbs`, `padiem-tunnel-wrapper.cmd`, `padiem-tunnel.cmd`, `scripts/ops/com2_mesh/tests/test_tunnel_launcher.ps1`, `scripts/ops/com2_mesh/README.md`. `padiem-tunnel.cmd`는 실행기 자체가 불필요하고, 저장소에 공개하면 안 되는 운영 접속 값이 들어 있어 복사·인용하지 않는다.

#5577은 2026-10-23 통합 링크와 이 표의 사유를 남기고 superseded로 종료했다(merged=false). #5578을 통합 기준으로 유지하며, #5577에서 추가 구현을 옮기지 않았다.

## 10. 최종 리뷰 (2026-10-23, PR #5578)

### 10.1 전환 불변식 확인

| 불변식 | 소스 근거 | fixture·CI 증거 | 실제 전환에서 남은 확인 |
|---|---|---|---|
| 단일 supervisor | `FileShare.None` 잠금, 중복 시 exit 2, IgnoreNew | 중복 거부·상태 보존 selftest, XML 불변식 검증 | Task Scheduler IgnoreNew의 런타임 동작(5.5.4, 5.7) |
| 리스너 소유권 | 준비 판정은 리스너 소유 PID == 자식 PID | 다른 프로세스 포트 점유 시 준비 실패 selftest | 전환 승인은 직접 PID 조회로만 판정(5.5.3) |
| 자식 수명 | job object `KILL_ON_JOB_CLOSE`, 생성·할당 실패는 치명적, 종료 시 직접 종료 | 미생성·미할당 시 자식 미기동, job 닫기 시 자식 회수 selftest | 5.6 강제 종료 게이트로 실제 기동 경로를 확인 |
| 잠금 해제 | OS 핸들 기반, 소유자만 잠금 파일 제거 | 비정상 종료 후 재기동 selftest | 실제 강제 종료 후 재기동(5.6.4) |
| 진행 작업 보존 | 엔진은 전달만 교체, 명령 결과 큐를 만들지 않음 | 해당 없음 | 창 시작 전 실행 중 작업 없음 확인(5.1.5)이 유일한 보장 |
| 기존 소비자 호환 | 필드 추가만, `recovery_ok=pending`은 성공 아님 | 소비자 필드 표(§3.6), read-only 확인 | health 스크립트 연결 후 실제 표시(5.8) |

### 10.2 발견 사항

분류: 코드 결함 **F1, F2**(이 HEAD에서 수정), 적용 전제 **F3, F4, F6**(§5.1.6, §5.4.5, §5.3), 운영 검증 항목 **F5, F7**(§5.7, §8). F5는 문서 기준을 이미 교체했으므로 코드 변경 없이 런타임에서 `NextRunTime`으로 확인한다.

| ID | 내용 | 영향 | 처리 |
|---|---|---|---|
| F1 | job object 생성·할당 실패가 치명적이지 않고 상태·로그에도 남지 않는다(fail-open). | ~~강제 종료 시 ssh 자식이 남을 수 있다.~~ | **해소**: 생성·할당 실패는 `job_object_unavailable`/`job_object_assign_failed`로 끝나며 자식을 기동·유지하지 않는다. selftest 66건에 포함. 5.6은 런타임 확인으로 유지. |
| F2 | `Wait-ForwardListener`는 연결 테이블 조회가 실패하면 TCP 연결 성공만으로 준비를 인정한다. | ~~다른 프로세스의 포트 점유를 구분하지 못한다.~~ | **해소**: TCP 대체를 제거하고 `netstat -ano` 소유 PID 대조로 교체했다. 소유 PID가 자식 PID와 같을 때만 준비로 인정한다. |
| F3 | 복구 엔진의 `restart_tunnel`은 작업 중지 → 리스너 PID 종료 → 작업 시작을 직접 수행한다. | 적용 창에서 감시자가 동시에 실행되면 전환 순서와 충돌한다. | 5.1.6에서 감시자를 식별하고 창 동안 비활성화한다. 적용 후에는 supervisor 자식이 `-L`·포트 조건을 만족하므로 기존 경로가 그대로 동작한다. |
| F4 | 기존 래퍼를 강제 종료하면 `padiem-tunnel.lock.d`가 남고, 복원된 래퍼는 rc=3으로 즉시 끝난다. | 롤백 실패로 오인할 수 있다. | 5.4.5에서 제거하고, R2~R5에 제거 조건을 넣었다. |
| F5 | 장기 실행 supervisor에서는 IgnoreNew 때문에 `LastRunTime`이 전진하지 않는다. | 구 §5.6의 반복 건강 기준이 성립하지 않는다. | 5.7에서 `NextRunTime` 전진, `LastTaskResult=267009`, supervisor PID 불변으로 대체했다. |
| F6 | supervisor 설정 기본 `tunnel_ssh_path`는 Windows OpenSSH이고 기존 체인은 Git ssh였다. | known_hosts·키 해석 차이로 전환이 실패할 수 있다. | 5.3에서 기존 체인이 사용한 ssh 경로를 명시하도록 고정했다. |
| F7 | 적용 계획의 수동 시작은 부팅 트리거 인과를 증명하지 않는다. 자동 시작 프로브도 수동/부팅 시작을 구분하지 못한다. | "자동 복구 완료"로 오보고할 위험. | 5.9와 §8에 통제된 재부팅 시험을 별도 승인 항목으로 유지한다. |

### 10.3 판정

`FINAL_REVIEW_CONDITIONALLY_READY` — 소스·fixture·정확한 HEAD 정책 CI는 통과했고, 운영 적용 전 확인해야 할 조건은 5.1.5(진행 작업 없음), 5.3(ssh 경로 명시), 5.5.3(직접 PID 소유권), 5.6(자식 회수 런타임 확인), 5.7(10분 관찰)이다. F1·F2는 해소됐고 남은 조건은 모두 적용 창의 런타임 게이트다. 이 단계에서 병합·운영 적용·프로세스 종료/재시작·재부팅·failover·알림 발송은 수행하지 않았다.

## 11. 자동 시작 프로브의 supervisor 표시 분리 (2026-10-23)

### 11.1 동기

`LastTaskResult=2147946720`(`0x800710E0`)은 IgnoreNew 정책에서 supervisor가 이미 실행 중이라 새 시작이 거부된 코드일 수 있다. COM1의 Task Scheduler Operational 로그 채널이 비활성화되어 있어 이벤트로 이 거부를 확인할 수 없다. 확인되지 않은 추정을 정상 실행으로 표시하면 안 되므로, 판정과 표시를 분리했다.

이 변경은 check 판정·`failed_checks`·`unverified_checks`·`auto_start_state` 계산 로직을 바꾸지 않는다. 기존 실패 판정은 그대로 유지되고, supervisor 현재 상태와 마지막 시작 시도를 읽기 전용 관측으로만 덧붙인다.

### 11.2 표시 분리 계약

`tunnel_task_last_result_ok` 판정 기준(`0 또는 267009`)은 변하지 않는다. 결과 코드 `2147946720`은 여전히 실패로 판정되고 `failed_checks`에 남는다. supervisor 표시는 이 판정과 별도로, 아래 세 조건이 모두 확인될 때만 정상 실행 상태로 표시한다.

- 리스너가 설정된 루프백 포트에 존재한다(`tunnel_listener_present` = true).
- 리스너 소유 프로세스 이름이 설정값과 일치한다(`tunnel_listener_process_matches` = true).
- 리스너 소유 자식 PID의 부모 프로세스 명령행에 supervisor 스크립트 이름(설정 키 `tunnel_supervisor_script`, 기본 `com2_mesh_tunnel_supervisor.ps1`)이 포함된다(identity = `confirmed`).

세 조건 중 하나라도 확인되지 않으면 supervisor 상태는 `unknown` 또는 `not_running`이 되고, identity는 `confirmed`/`unconfirmed`/`mismatch` 중 하나로 기록된다. `running_connected`/`running_disconnected`/`running_connection_unknown`는 identity가 `confirmed`일 때만 나온다.

### 11.3 suspected/confidence 의미

마지막 시작 시도(`last_start_attempt`)는 원래 결과 코드와 시각을 보존한다. `result`(정수 코드), `result_hex`, `run`(마지막 실행 시각)은 관측값 그대로이고, 판정을 위해 재작성하지 않는다.

`outcome`과 새 `confidence` 필드는 다음과 같다.

- `2147946720`이고 supervisor·자식·리스너 체인이 `confirmed`+정상 상태로 확인되면 `outcome=suspected_refused_while_running`, `confidence=suspected`. 이벤트를 읽지 못했으므로 추정임을 값으로 드러낸다.
- `2147946720`이고 체인이 확인되지 않으면 `outcome=failed`, `confidence=observed`. 거부 추정조차 성립하지 않는다.
- `0`/`267009`/`267011`/`267010`/`2` 등 나머지 코드는 기존 outcome을 유지하고, 코드가 정수로 파싱되면 `confidence=observed`, 파싱되지 않으면 `confidence=unknown`.

### 11.4 새 레코드 필드

프로브 레코드에 두 하위 객체를 추가했다. 기존 필드는 제거하지 않았다.

- `supervisor`: `state`, `identity`, `identity_detail`, `child_pid`, `child_process`, `parent_pid`, `detail`.
- `last_start_attempt`: `run`, `result`, `result_hex`, `outcome`, `confidence`, `detail`.

리스너 관측(`Get-ListenerObservation`)에는 `parent_pid`, `parent_process_name`, `parent_command_line_observed`, `parent_runs_supervisor`, `parent_error`를 추가했다. 부모 명령행은 조회 직후 메모리에서 supervisor 스크립트 이름과 대조하고 버린다. 관측·레코드에는 명령행을 읽었는지 여부(`parent_command_line_observed`)와 대조 결과(`parent_runs_supervisor`)만 남고, 전체 명령행 문자열이나 그 안의 경로·인자·비밀값은 기록하지 않는다. 부모 조회가 실패해도 리스너 관측 자체는 유효하게 유지되고 `parent_error`에만 실패 사유를 기록한다.

### 11.5 health 표시 연결 (재현 가능한 저장소 변경)

운영 health 스크립트는 저장소 밖에 있어 직접 수정하지 않는다. 대신 재현 가능한 저장소 변경으로 세 파일을 추가했다.

- `scripts/ops/com2_mesh/com2_mesh_health_display.ps1`: 표시 모듈. `Get-AutostartDisplayClass`, `Add-AutostartDisplayFields`, `New-AutostartDisplayRows`. 판정 필드는 건드리지 않고 supervisor/시도 표시 필드와 HTML 행만 덧붙인다.
- `scripts/ops/com2_mesh/com2_mesh_health_patch.ps1`: 해시 보호 앵커 기반 패치 적용기. `-HealthScript`(필수), `-ExpectedSha256`(기본 `44914F0CBB142CA71596A0D0368B0B797C547B1389C4211FC0C2169DCFE737F5`), `-Apply` 스위치. 기본은 dry run이고, 해시 불일치·파일 없음·앵커 모호 시 exit 1.
- `scripts/ops/com2_mesh/com2_mesh_health_display_selftest.ps1`: fixture 기반 selftest. 합성 fixture로 dry run/apply/구문 검사/실행 결과를 검증한다.

패치 적용기는 운영 health 스크립트의 base SHA256 `44914F0C…`(LF, BOM 없음)을 기대 해시로 고정하고, 상태 복사 블록(앵커 A, base line 250)과 자동 시작 HTML 행(앵커 B, base line 285) 두 지점만 교체한다. 원본 EOL·UTF8(no BOM)을 보존하고, 적용 전 `.bak-yyyyMMdd-HHmmss` 백업을 만든다. 표시 모듈이 health 스크립트 옆에 배포되지 않으면 패치는 비활성 상태로 남아 기존 동작을 바꾸지 않는다.

### 11.6 테스트·변형 증거

- `com2_mesh_autostart_selftest.ps1`: 185 PASS / 0 FAIL. baseline, UInt32 오류(`suspected_refused_while_running`/`suspected`, 코드·시각 보존), `identityUnknown`(부모 pid 0), `identityNoCommand`(부모 명령행 빈 값), `identityMismatch`(다른 스크립트), `ownerUnknown`(소유 프로세스 이름 빈 값) fixture를 포함한다. 기존 실패 판정 보존을 단정한다.
- `com2_mesh_health_display_selftest.ps1`: 90 PASS / 0 FAIL. 표시 클래스 계약, 필드 복사 계약, 프로브 end-to-end, 패치 적용기(dry run 불변 해시, `DEADBEEF` 거부, 앵커 없음 거부, apply 후 구문 오류 0, 실행 결과 필드/HTML 추가, 모듈 없이 실행 시 무충돌)를 포함한다.
- 변형 테스트: 프로브(outcome 이름, confidence, 코드 매처, identity 게이트, 명령행 일치, 부모 pid 누락)와 표시 모듈(ok 클래스가 identity 무시, 구형 스키마→running, result 소거, confidence 강제) 변형을 모두 주입해 해당 테스트가 실패함을 확인했다. 부모 명령행 빈 값 분기의 초기 변형이 탈출해 `identityNoCommand` fixture를 추가했고, 이후 해당 변형은 4건에서 실패한다.
- 패치 적용기는 운영 base의 임시 사본에서 dry run(파일 불변)과 apply(백업 해시 = base, 새 해시 `F6D4C9FA77AEECB4D8C1B3430D4DD3AD6A60117B63CFB8455D53377306602CEF`, parse_errors=0)를 검증한 뒤 임시 사본을 제거했다.

### 11.7 범위 밖 확인 상태

이 단계에서 수행하지 않은 것: 운영 적용, Task Scheduler 로그 채널 활성화, 프로세스 종료/재시작, 재부팅, failover, 알림 발송. 패치 적용기는 저장소 변경일 뿐 운영 health 스크립트에 적용하지 않았다.

확인되지 않은 것(UNVERIFIED): 부팅 자동 시작, 재부팅 복구, 24시간 지속성. 이들은 읽기 전용 관측으로 증명할 수 없고 §5.9·§8의 통제된 재부팅 시험이 별도 승인 항목으로 남는다. `suspected_refused_while_running`는 이벤트 확인이 아닌 supervisor·자식·리스너 체인 관측에 기반한 추정이다.
