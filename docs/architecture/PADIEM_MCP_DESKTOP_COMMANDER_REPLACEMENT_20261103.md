# PADIEM MCP로 Desktop Commander 대체 — 1단계 PC 명령 실행

작업일: 2026-11-03  
범위: `pc_shell` 1종, 기존 MCP 게이트웨이·승인·PC 명령 전달 재사용, 시험·문서.  
비범위: OAuth 2.1 웹 커넥터 로그인, 장시간 프로세스 도구, 대용량 파일 전송.

## 1. 지금 있는 도구

| MCP 도구 | 인자 | 실행 경로 |
| --- | --- | --- |
| `pc_list` | `path` | Engine PC 파일 계획 → 서명된 Engine→Chat callback → Connector/Mesh |
| `pc_search` | `path`, `query` | 위 목록 결과의 바로 아래 이름 검색 |
| `pc_read` | `path` | `claw.pc.read_file` |
| `pc_write` | `path`, `content` | `claw.pc.write_file` |
| `pc_move` | `path`, `destination` | `claw.pc.move_file` |
| `pc_delete` | `path` | `claw.pc.delete_file` |
| `pc_browser_open`·`read`·`screenshot`·`act` | 브라우저 인자 | `claw.pc.browser_*` |
| **`pc_shell`** | `command`, `cwd?`, `shell?`, `timeout_seconds?` | Chat oracle_mesh 명령 레인 직접 사용 |

`pc_shell`의 `shell`은 `powershell`(기본)·`cmd`·`bash`, 인자는 `command`(필수)·`cwd`·`shell`·`wait_seconds`(기본 120·최대 600)다. `timeout_seconds`라는 이름의 실행 상한은 3단계에서 사라졌다 — `wait_seconds`는 **응답을 기다리는 시간**이고 명령 실행에는 상한이 없다. 스키마는 닫혀 있고 `additionalProperties: false`다. 등록은 `apps/padiem-chat/app/mcp_gateway_transport.py`의 `_tool`을 그대로 쓴다.

## 2. pc_shell 동작

1. `mcp_gateway_execution.execute_mcp_pc_tool`이 기존 MCP token/PC/세션 확인을 먼저 수행한다. 토큰의 PC가 연결·승인 상태가 아니거나, 현재 선택된 실행 PC와 다르거나, Mesh grant가 없으면 실행하지 않는다(`chat_pc_target_unavailable`).
2. `pc_shell`은 Engine 계획을 만들지 않고 Chat의 기존 명령 디스패치(`dispatch_oracle_mesh_command_intent`)로 한 번 보낸다. Engine 도구 계약을 늘리지 않고, 데스크톱 레인이 이미 쓰는 명령 전달·결과 저장·소유자 확인을 그대로 쓴다.
3. 사용자 명령은 UTF-8 Base64로만 전달한다. 디스패치 명령 한 줄에는 원문 명령이 들어가지 않는다. `cwd`도 Base64다.
4. PC의 작업 스크립트는 선택한 셸을 자식 프로세스로 띄우고 stdout·stderr를 각각 파일로 받는다. `powershell`은 BOM 있는 `.ps1`과 `-File`로 실행해 Windows PowerShell 5.1에서도 오류 출력이 CLIXML로 바뀌지 않게 했다. `cmd`는 `chcp 65001`·`@echo off`, `bash`는 UTF-8 스크립트를 쓴다.
5. 부모 cmd가 자식의 종료 코드를 지연 확장(`!ERRORLEVEL!`)으로 별도 파일에 기록한다. 사용자 명령이 `exit N`으로 끝나도 코드가 보존된다.
6. 기다림은 **응답**에만 걸고 명령에는 걸지 않는다(대표 결정 2026-10-24). `wait_seconds` 안에 끝나면 종료 코드를 돌려주고, 시간이 지나면 명령을 죽이지 않고 PC에서 계속 실행하게 둔 뒤 작업 번호와 지금까지의 출력을 돌려준다. 프로세스 트리 종료(`taskkill /T /F /PID`, DesktopCommanderMCP의 `force_terminate` 설계)는 사용자가 `pc_shell_stop`으로 명시적으로 중지할 때만 일어난다.
7. 한 번의 응답은 스트림별 12,000바이트 상한을 쓴다. 끝난 명령은 앞·뒤를 남기고 `...[중간 생략]...`을 넣는다. 아직 실행 중인 명령의 미리보기는 앞쪽만 잘라 `next_offset`을 이어 읽을 수 있게 한다. 원래 바이트 수와 절단 여부를 함께 돌려준다. JSON 전체가 기존 작은 결과 저장 한도(65,536바이트) 안에 들어가므로 결과 조회가 안정적이다.
8. MCP 결과는 `status`, `job_id`, `state`, `running`, `exit_code`, `stdout`, `stderr`, `stdout_bytes`, `stderr_bytes`, `truncated`, 서버 측 `duration_ms`, PC 측 `pc_duration_ms`를 포함한다. 명령이 0이 아닌 코드로 끝난 것은 실행 실패가 아니라 완료된 실행으로 보고한다.

## 3. 권한과 승인

- 사전 위임의 단위는 **이 MCP 토큰이 가리키는 연결·승인된 PC**다. 토큰 폐기, PC 연결 해제, Mesh grant 없음, 실행 PC 불일치에서는 실행하지 않는다.
- 어떤 명령이 비밀번호 입력·계정 권한 변경·되돌릴 수 없는 삭제·외부 발송인지 서버가 자동 판정하지 않는다. 오탐으로 정상 작업을 막지 않기 위해서다. 도구 설명과 MCP `instructions`에 원칙을 적고, 위험 작업은 실행 전에 PADIEM 대화에서 확인한다.
- 기존 승인 receipt 경로는 그대로 남아 있다. 외부 AI가 같은 도구·인자로 재시도하면 `mcp_gateway_dispatch`가 정확한 승인 하나를 원자적으로 소비한다. `pc_shell`은 승인 receipt를 요구하지 않으며, 위임된 PC에서 바로 실행한다.

## 4. 감사

- 기존 `padiem_mcp_audit` 행에 도구 이름·요청 digest·상태·승인 ID를 남긴다.
- `094_mcp_shell_audit.sql`이 `exit_code`, `duration_ms`, `output_bytes`, `output_truncated` nullable 컬럼을 추가한다. 명령 본문과 출력 내용은 저장하지 않는다.
- `padiem_chat.request`의 `mcp_operation` 로그에도 같은 숫자 필드만 넣는다. `request_digest`는 해시다. 명령·출력은 로그에 없다.
- 배포 전에 migration 094를 적용해야 한다. 094가 없는 DB에서는 outcome 감사 insert가 실패해 `audit_status=unavailable`로 표시되고, 요청 감사도 실패하면 도구는 실행되지 않는다.

## 5. PC 실행 수단 판정

- Engine 파일 도구는 **검토된 고정 Mesh 명령**만 실행한다(`kagent.pc_query_adapter`의 도구 계약). 임의 명령을 넣을 자리가 없다.
- Chat의 `dispatch_oracle_mesh_command_intent`는 기존 터미널 레인으로, 명령 텍스트를 `oracle_mesh_dispatch` 행에 넣고 Connector가 실행한다. `pc_shell`은 이 경로를 재사용했다.
- Connector 실행: `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py`의 명령 실행과 `local_agent_meshcentral_command_port.py`의 `run_command`/`_wrap`이 `powershell -command -`에 스크립트를 넣고 stdout+stderr를 Base64 envelope로, `$LASTEXITCODE`를 sentinel로 돌려준다. 이 경로는 한 번 실행이고, 서버가 자식 프로세스의 stdin/핸들을 유지하지 않는다.
- 기존 PowerShell literal 헬퍼(`_pc_files_powershell_literal`)는 서버가 만든 고정 스크립트용이다. 임의 명령을 그 안에 직접 넣으면 이스케이프 경계가 사용자 입력에 열리므로, pc_shell은 Base64 전달과 고정 worker 스크립트를 쓴다.

## 6. 장시간 프로세스 도구 조사

DesktopCommanderMCP(MIT, https://github.com/wonderwhy-er/DesktopCommanderMCP)의 `start_process`, `read_process_output`, `interact_with_process`, `force_terminate` 구현을 확인했다. 핵심 설계는 다음과 같다.

- `TerminalManager.executeCommand`: 프로세스를 띄우고 wait 상한까지 기다린 뒤 PID와 출력 상태를 돌려준다. 출력은 줄 단위 버퍼(상한 50MB)에 쌓고 오래된 줄부터 버린다.
- `readOutputPaginated`: `offset`/`length`, 음수 offset(끝에서), offset 0(마지막 읽은 뒤)으로 이어 읽고 남은 줄 수를 알려준다.
- `sendInputToProcess`: 살아 있는 자식의 stdin에 쓴다.
- `forceTerminate`/`terminateProcessTree`: Windows는 `taskkill /T /F`, POSIX는 SIGTERM 후 SIGKILL로 트리를 끝낸다.
- 출력이 wait 버퍼를 넘으면 잘림 안내를 붙인다.

이번 1단계에서는 `pc_shell_start/read/stop`을 구현하지 않았다. 이유는 우리 Mesh 명령 레인이 **한 번 실행**이고, 서버가 자식 프로세스의 stdin·출력 핸들을 다음 도구 호출까지 유지할 수 없기 때문이다. PID/작업 소유권을 안전하게 묶을 durable job 저장소도 새로 필요하다. 2단계 설계는 기존 `oracle_mesh_dispatch` 행을 job 소유권으로 쓰고, PC에 `%TEMP%\padiem-shell-jobs\<dispatch_id>\` 로그 파일을 두어 offset/길이로 읽으며, stop은 그 행의 PID 파일을 `taskkill /T /F`로 끝내는 방식이 적합하다. `interact_with_process`는 PC에 상주형 브로커가 생기기 전까지 제공하지 않는다.

3단계에서 이 설계를 실행했다(§11). PC에 상주형 브로커를 만들지 않고 같은 결론에 닿도록, 자식을 **detach해서 PC의 작업 폴더에 출력을 쌓는** 방식으로 바꿨고, job 키는 재사용하지 않는 `mcpjob_<32hex>`와 새 내구 행으로 묶었다. Executor에는 이미 `RemoteBackgroundJobs`(`packages/padiem-ai-core/padiem_ai_core/pc_background.py`)가 있지만 출력 파일을 **러너가 끝난 뒤 한 번** 쓰고, `background=True`는 queue 스토어(`queue_background_dispatch`)에서만 동작해 기본 Chat 스토어에서는 디스패치 자체가 실패한다. 그래서 그 경로를 확장하는 대신 기존 한 번 실행 디스패치를 그대로 쓰고 PC 쪽에서만 계속 실행되게 했다.

## 7. OAuth 2.1 설계 메모 (2단계)

지금은 개인 Bearer 토큰(PAT)이다. claude.ai·ChatGPT 웹 커넥터가 MCP 인증 사양대로 붙으려면 다음이 필요하다.

- Protected Resource Metadata로 `resource`와 authorization server를 알린다.
- Authorization Code + PKCE, 동적 클라이언트 등록(또는 사전 등록), `resource` 파라미터와 audience 바인딩.
- 승인 화면에서 사용자·PC·범위를 확인하고, 발급 토큰은 기존 `padiem_mcp_tokens`/scope 검증에 연결한다.
- 토큰 회전·폐기·감사는 기존 경로를 재사용한다.

이번 범위는 아니다. Claude Code·Codex처럼 Bearer 헤더를 설정할 수 있는 MCP 클라이언트는 지금 연결할 수 있다.

## 8. 연결 방법

1. PADIEM 설정의 **외부 AI 연결**에서 연결 이름과 내 PC를 고른다.
2. 개인 토큰을 발급한다. 토큰은 한 번만 표시된다.
3. 클라이언트의 MCP HTTP 설정에 표시된 `/api/mcp` 주소와 `Authorization: Bearer <토큰>`을 넣는다. 토큰을 URL·인자·소스·로그에 남기지 않는다.
4. PC가 연결·승인 상태이고 선택된 실행 PC가 토큰의 PC와 같아야 도구가 실행된다.

## 9. 남은 것

- OAuth 2.1 authorization server + 웹 커넥터 로그인(2단계 브랜치 `feat/mcp-oauth-261103`).
- 커넥터 게이트웨이 WebSocket의 **명령 프레임**(§11.5). 지금은 등록 전용이라 늘 연결된 PC로도 기존 디스패치 큐를 쓴다.
- 대용량 출력·파일의 청크/스트리밍 전송과 대화형 stdin(`interact_with_process`에 해당).
- Windows·macOS·Linux 셸별 실기기 검증(이번 PC worker 시험은 Windows PowerShell·cmd·Git Bash에서 수행).

## 10. 검증

- `tests/test_mcp_gateway_*.py`, `tests/test_mcp_browser_*_3782.py`, `tests/test_mcp_pc_shell_261103.py`: 129 passed.
- 새 시험 16건: 닫힌 스키마, 위임/연결 거부, 완료·절단·오류·시간 초과, audit 숫자 필드, DB audit 비밀 부재, Windows 실제 worker(PowerShell exit code·stderr·cwd·절단·시간 초과·cmd·bash).
- Windows 기본 인코딩(cp949) 때문에 실패하던 기존 MCP 설정/왕복 시험은 파일 읽기와 자식 `PYTHONIOENCODING`을 UTF-8로 고정해 통과시켰다. 제품 코드 변경이 아니라 시험 환경 수정이다.

참고: DesktopCommanderMCP(MIT). 이 저장소에는 그 소스 코드를 복사하지 않았고, 위에 적은 실행 형태(대기 상한, 출력 상한·절단, 프로세스 트리 종료)만 새 Python/PowerShell 코드로 구현했다. 따라서 `static/third-party-licenses.html`에는 새 항목을 추가하지 않았다. 런타임 의존성도 추가하지 않았다.

## 11. 3단계 실행: 시간 제한 없는 명령과 이어 읽기 (2026-11-03)

### 11.1 원칙

- 대표 결정(2026-10-24)대로 PC 도구 작업에는 **실행 시한을 두지 않는다**. 오래 걸리면 진행 중과 경과 시간을 보여 주고, 끝내는 사용자의 `pc_shell_stop` 또는 PC 연결 해제만으로 일어났다.
- 600초는 실행 상한에서 **응답 대기 상한**으로 내려왔다. 도구 인자 이름도 `timeout_seconds` → `wait_seconds`로 바꿨다(아직 운영에 나가지 않은 스키마라 이름 변경 부담은 없다).
- 기다림이 끝났다고 명령을 죽이거나 실패로 보고하지 않는다. 같은 응답에 작업 번호와 지금까지의 출력을 담는다.

### 11.2 네 도구

| MCP 도구 | 인자 | 돌려주는 것 |
| --- | --- | --- |
| `pc_shell` | `command`, `cwd`, `shell`, `wait_seconds` | 끝나면 stdout·stderr·종료 코드, 안 끝나면 작업 번호 + 지금까지 출력 + `next_offset` |
| `pc_shell_start` | `command`, `cwd`, `shell` | 기다리지 않고 작업 번호(명령은 PC에서 계속, 실행 시간 제한 없음) |
| `pc_shell_read` | `job_id`, `offset`, `length`, `stream` | 그 위치 이후 출력 조각, `next_offset`·`eof`·상태(실행 중/종료·종료 코드)·경과 시간 |
| `pc_shell_stop` | `job_id` | 프로세스 트리 종료(`taskkill /T /F`)·최종 상태, 아직 PC에 닿지 않은 대기 작업이면 디스패치 취소 |

등록·승인·감사 경로는 1단계와 같다(`_tool` 등록, `mcp_gateway_dispatch`, `padiem_mcp_audit`). `pc_shell_read`는 `readOnlyHint`, 나머지는 `destructiveHint`로 표시한다. `pc_shell_read`는 커서 폴링이라 대화 공지에 같은 문구를 반복해서 쌓지 않는다.

### 11.3 PC 쪽 작업 파일

`%LOCALAPPDATA%\padiem-mcp-jobs\`(없으면 임시 폴더) 안에 작업 번호별로 `.out`·`.err`·`.code`·`.meta`·`.killed`·`.ps1|cmd|sh`를 둔다.

- 시작은 `Start-Process cmd.exe -WindowStyle Hidden -PassThru`(재사용 가능한 `NoNewWindow`·리다이렉트 조합 대신 숨긴 창으로 띄워)로 **detached** 자식을 만들고, 자식의 stdout·stderr를 그 파일로 보낸다. 부모 worker와 디스패치가 끝나도 파일은 계속 자란다.
- `.meta`는 `{pid, started_at_ms}`. `.code`는 wrapper cmd가 지연 확장으로 쓴 종료 코드. `.killed`는 stop이 트리를 끝냈다는 표식. 상태 판정은 파일 + `Get-Process -Id`로 한다: `.code` 있으면 exited, `.killed` 있으면 cancelled, pid 살아 있으면 running, 아니면 lost(PC 재시작 등).
- 이어 읽기는 `FileShare.ReadWrite`로 열어 `offset`/`length`(최대 65,536바이트)만큼만 잘라 준다. 미리보기 절단(12,000바이트)과 달리 이어 읽기는 앞쪽만 잘라 커서가 이어진다.
- 정리는 두 갈래뿐이다. 사용자가 stop한 뒤 30일이 지난 파일, 그리고 30일이 지나고 실행 중이 아닌 파일은 worker가 지운다(`Remove-PadiemOldJobs`). 실행 상한이 없는 대신 **파일 보존 기간**만 존재한다. 총 출력이 64MB를 넘으면 `large: true`로 알려 준다(디스크를 채우지 않도록 정리를 유도하는 표시이고, 명령을 죽이지는 않는다).
- worker 스크립트는 gzip+Base64로 보내 TEMP에 `.ps1`로 풀어 `-File`로 실행한다. `-EncodedCommand`에 그대로 넣으면 이 스크립트가 Windows 명령줄 상한(32,767자)을 넘긴다.

### 11.4 작업 소유권 — `096_mcp_shell_jobs.sql`

`padiem_mcp_shell_jobs(id, user_id, token_id, device_id, run_id, dispatch_id, command_sha256, shell, state, exit_code, created_at, updated_at, finished_at)`.

- 행은 **명령을 보내기 전**에 쓴다. 디스패치가 중간에 죽어도 추적 없는 프로세스가 남지 않고, 사용자는 여전히 번호로 보고 중지할 수 있다.
- `dispatch_id`는 한 번만 박힌다(`attach_shell_job_dispatch`의 조건부 UPDATE). 다시 보내도 다른 디스패치로 바뀐다.
- `read`·`stop`은 `get_shell_job(job_id, user_id)`로 자기 계정 행만 찾고, `device_id`가 이 토큰의 PC와 다르면 **없는 번호와 같은 답**(`pc_shell_job_not_found`)을 돌려준다. 다른 계정·다른 PC의 작업 번호로는 읽기도 중지기도 안 된다.
- `state`는 `queued|running|exited|cancelled|lost` CHECK. 끝난 행은 되살리지 않는다. 명령 본문은 `command_sha256` digest만 남기고, 출력은 이 표에 저장하지 않는다(PC의 파일과 기존 oracle_mesh 결과 저장소가 담당).
- 계정 탈퇴 정리 목록(`account_deletion._USER_KEYED_TABLES`)에 추가했다.
- `run_id`는 시작 호출의 lane run id를 저장한다. 꺼진 PC에 대기 중인 작업을 stop할 때 `cancel_oracle_mesh_dispatches_for_run(user_id, run_id)`가 그 명령 하나만 취소한다(호출마다 새 run을 만들기 때문에 이 저장된 run id가 필요하다).

### 11.5 늘 연결된 통로 판정

조사 결과(이 브랜치 코드 기준):

- 커넥터 게이트웨이 `WebSocket /api/claw/connector/gateway/session`은 **등록 전용**이다. 실리는 프레임은 `_BEGIN/_FINISH/_FETCH/_ACK/_BEGIN_RECEIPT/_FINISH_RECEIPT/_ACTION_RECEIPT/_BINDING`뿐이고 세션은 `paired_offline`으로 끝난다(`connector_gateway_websocket_session.py`). 명령·결과 프레임은 없다.
- Chat 쪽에 device→live socket 레지스트리가 없다. 산재 신호는 D1 `mesh_device_presence`(`upsert`/`load`, 180초 상한)이고, 커넥터가 ≤5초 폴(`POST /api/claw/connector/mesh-reads/poll`)으로 갱신한다. 커넥터 쪽 프로덕션 다이얼러도 꺼져 있다(`WSS_PRODUCTION_DIALER_ENABLED = False`, `device_wss_enrollment.py`에 "NO production WebSocket is constructed here").
- 호스트 플래그 `PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED`는 기본 off이고(#6380 문서, `BROKER_GAP_TABLE_20261031`), Worker 경로(`PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED`·`RELEASE_SCOPE`)도 `PRODUCTION_GATEWAY_DEFAULT_ON = False`다.

그래서 "게이트웨이에 연결된 PC면 게이트웨이로 바로"는 지금 프레임이 없어 실행할 수 없고, 같은 질문에 실제로 답할 수 있는 신호를 판정에 썼다(`_pc_lane_is_live`):

- PC가 **살아 있으면**(fresh beat): 기존 디스패치가 ≤5초 안에 클레임되므로 그대로 두면서 대기 창을 다 쓴다.
- PC가 **없으면**: `pc_shell`(대기형)은 실행하지 않고 `pc_shell_pc_offline`으로 정직하게 답한다. `pc_shell_start`는 큐로 남긴다(디스패치 TTL 3600초 안에서 PC가 돌아오면 실행). `pc_shell_read`는 내구 행으로 상태·경과만 보여 주고 커서를 보존한다. `pc_shell_stop`은 클레임 전이면 큐 행을 취소하고, 실행 중이면 PC가 돌아올 때까지 중지할 수 없다고 답한다.
- 앞으로 게이트웨이 명령 레인이 붙을 자리는 한 곳이다: `dispatch_oracle_mesh_command_intent`에서 `target = mesh_source.command_target(...)`를 해석한 직후(1260줄 근처). "이 node에 라이브 소켓이 있으면 프레임을 쓰고, 없으면 지금처럼 디스패치 행을 만든다"로 갈라야 하며, 그보다 앞(MCP 소유권·grant·device 확인)과 뒤(결과 저장·감사)는 그대로 재사용된다. 이번 단계에서 그 분기를 만들지는 않았다.

### 11.6 앞단(padiem-chat-front)

- `POST /api/mcp`는 8초 기본 쓰기 마감으로는 PC 도구를 받을 수 없다. 대기형 호출이 정상인데 앞단이 504를 내고, 504를 본 외부 클라이언트가 재시도하면 명령이 두 번 돈다. `MCP_TIMEOUT_MS`(기본 180,000ms) 분기를 추가했다. 새 wrangler 변수는 아니고 코드 기본값이라 변수 계약 시험은 그대로 통과한다.
- 커넥터 게이트웨이 WebSocket은 앞단이 이미 컴2로 넘긴다: upgrade 요청은 `streaming`으로 판정돼 읽기 분기를 타고, 101 응답은 fetch가 만든 **그대로의 객체**로 반환된다(Cloudflare는 101을 다시 만들 수 없다). 정적 분기에도 닿지 않는다. 이 두 사실을 시험으로 고정했다.
- OAuth 브랜치(`feat/mcp-oauth-261103`)가 같은 `timeoutMs` 체인을 수정한다. 머지 순서가 겹치면 두 분기(`oauthRequest`, `mcpToolCall`)가 나란히 들어가도록 푼다.

### 11.7 운영 반영 때 할 일

1. migration 순서: 094(pc_shell 감사) → 095(OAuth, 다른 브랜치) → **096(이 작업)**. 096 없이는 `create_shell_job`이 실패해 셸 도구가 실행하지 않는다.
2. 앞단 `apps/padiem-chat-front` 재배포: `POST /api/mcp` 180초 분기가 들어 있다.
3. 게이트웨이 WSS를 켜야 한다면 순서는 별도 결정이다: 신뢰 엣지가 클라이언트 proof 헤더를 벗기고 → `PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED=true` + `PADIEM_COM2_EDGE_SECRET_FILE`·`PADIEM_COM2_IDENTITY_RPC_SECRET_FILE`·`PADIEM_COM2_BROKER_RPC_SECRET_FILE` + 내구성 `PADIEM_COM2_EDGE_REPLAY_DB` → 커넥터 다이얼러 production gate → **명령 프레임 신설**(§11.5). 이 레인은 아무것도 켜지 않았다.
4. 실PC 확인: `pc_shell_start`로 10분 넘는 명령을 띄우고 `pc_shell_read`로 이어 읽기, 다른 PC·다른 계정의 작업 번호 거부, stop 뒤 트리 소멸, 앞단 504 없이 완료.
5. 설치 토큰(PR-4 #6695)·PC 연결 소유권으로 게이트웨이 경로에서도 남의 PC에 닿지 않게 해야 한다(프레임이 없어 이번 단계에서는 검증하지 못했다).

### 11.8 검증

- `tests/test_mcp_pc_shell_261103.py` 37건: 닫힌 스키마 4종, gzip worker 한 줄(원문 명령 미포함), envelope 파서 세 형태, 실제 `dsp_*` 디스패치 번호 인정(1단계 시험은 `oracle_mesh_cmd_*`를 써서 이 버그를 잡지 못했다), 완료·절단·worker 오류, 대기 초과 → 작업 인도(취소 없음), 꺼진 PC 거부, start 즉시 반환·큐, offset 연속 읽기, 다른 계정·다른 PC 번호 거부, 꺼진 PC의 read가 행으로 답하고 커서 보존, stop의 트리 종료·대기 취소, 감사 숫자만(로그·DB), SQLite job 행 소유권, Windows 실제 worker(detached 생존 + offset 읽기 + taskkill + cmd/bash + 잘못된 job id 거부).
- 회귀 묶음 238 passed: MCP gateway/transport/execution/roundtrip/settings UI/browser, pc_delegation 3종, 계정 탈퇴, 만료 정리, 도움말.
- 앞단: `node --test apps/padiem-chat-front/test/*.test.mjs` 65 passed(신규 7건 포함).
- 디스패치 번호 버그 고정(`oracle_mesh_cmd_*` → `dsp_*`) 없이 1단계 pc_shell은 성공한 디스패치를 항상 `pc_shell_dispatch_refused`로 보고했다. 이번 시험이 그 형태를 직접 확인한다.
