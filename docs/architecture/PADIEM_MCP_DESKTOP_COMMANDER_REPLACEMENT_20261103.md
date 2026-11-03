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

`pc_shell`의 `shell`은 `powershell`(기본)·`cmd`·`bash`, `timeout_seconds`는 기본 120·최대 600이다. 스키마는 닫혀 있고 `additionalProperties: false`이며 `command`만 필수다. 등록은 `apps/padiem-chat/app/mcp_gateway_transport.py`의 `_tool`을 그대로 쓴다.

## 2. pc_shell 동작

1. `mcp_gateway_execution.execute_mcp_pc_tool`이 기존 MCP token/PC/세션 확인을 먼저 수행한다. 토큰의 PC가 연결·승인 상태가 아니거나, 현재 선택된 실행 PC와 다르거나, Mesh grant가 없으면 실행하지 않는다(`chat_pc_target_unavailable`).
2. `pc_shell`은 Engine 계획을 만들지 않고 Chat의 기존 명령 디스패치(`dispatch_oracle_mesh_command_intent`)로 한 번 보낸다. Engine 도구 계약을 늘리지 않고, 데스크톱 레인이 이미 쓰는 명령 전달·결과 저장·소유자 확인을 그대로 쓴다.
3. 사용자 명령은 UTF-8 Base64로만 전달한다. 디스패치 명령 한 줄에는 원문 명령이 들어가지 않는다. `cwd`도 Base64다.
4. PC의 작업 스크립트는 선택한 셸을 자식 프로세스로 띄우고 stdout·stderr를 각각 파일로 받는다. `powershell`은 BOM 있는 `.ps1`과 `-File`로 실행해 Windows PowerShell 5.1에서도 오류 출력이 CLIXML로 바뀌지 않게 했다. `cmd`는 `chcp 65001`·`@echo off`, `bash`는 UTF-8 스크립트를 쓴다.
5. 부모 cmd가 자식의 종료 코드를 지연 확장(`!ERRORLEVEL!`)으로 별도 파일에 기록한다. 사용자 명령이 `exit N`으로 끝나도 코드가 보존된다.
6. 제한 시간은 PC에서 강제한다. 시간을 넘으면 `taskkill /T /F /PID`로 프로세스 트리를 끝내고 `timed_out: true`, `exit_code: null`로 돌려준다. 이는 DesktopCommanderMCP의 `force_terminate`/`terminateProcessTree` 설계를 따른 것이다.
7. 출력은 스트림별 12,000바이트 상한으로 앞·뒤를 남기고 `...[중간 생략]...`을 넣는다. 원래 바이트 수와 절단 여부를 함께 돌려준다. JSON 전체가 기존 작은 결과 저장 한도(65,536바이트) 안에 들어가므로 결과 조회가 안정적이다.
8. MCP 결과는 `status`, `exit_code`, `timed_out`, `stdout`, `stderr`, `stdout_bytes`, `stderr_bytes`, `truncated`, 서버 측 `duration_ms`, PC 측 `pc_duration_ms`를 포함한다. 명령이 0이 아닌 코드로 끝난 것은 실행 실패가 아니라 완료된 실행으로 보고한다.

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

- OAuth 2.1 authorization server + 웹 커넥터 로그인.
- 장시간 프로세스 `pc_shell_start/read/stop`(위 설계).
- 대용량 출력·파일의 청크/스트리밍 전송.
- Windows·macOS·Linux 셸별 실기기 검증(이번 PC worker 시험은 Windows PowerShell·cmd·Git Bash에서 수행).

## 10. 검증

- `tests/test_mcp_gateway_*.py`, `tests/test_mcp_browser_*_3782.py`, `tests/test_mcp_pc_shell_261103.py`: 129 passed.
- 새 시험 16건: 닫힌 스키마, 위임/연결 거부, 완료·절단·오류·시간 초과, audit 숫자 필드, DB audit 비밀 부재, Windows 실제 worker(PowerShell exit code·stderr·cwd·절단·시간 초과·cmd·bash).
- Windows 기본 인코딩(cp949) 때문에 실패하던 기존 MCP 설정/왕복 시험은 파일 읽기와 자식 `PYTHONIOENCODING`을 UTF-8로 고정해 통과시켰다. 제품 코드 변경이 아니라 시험 환경 수정이다.

참고: DesktopCommanderMCP(MIT). 이 저장소에는 그 소스 코드를 복사하지 않았고, 위에 적은 실행 형태(대기 상한, 출력 상한·절단, 프로세스 트리 종료)만 새 Python/PowerShell 코드로 구현했다. 따라서 `static/third-party-licenses.html`에는 새 항목을 추가하지 않았다. 런타임 의존성도 추가하지 않았다.
