# PADIEM MCP로 Desktop Commander 대체 — 1·2단계

작업일: 2026-11-03  
범위: `pc_shell` 1종, 기존 MCP 게이트웨이·승인·PC 명령 전달 재사용, OAuth 2.1 웹 커넥터, 시험·문서.  
비범위: 장시간 프로세스 도구, 대용량 파일 전송, CIMD·OIDC ID 토큰.

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

### 3-1. 이번 단계에서 의도적으로 적용하지 않은 것 (대표 결정 2026-11-03)

- **`pc_shell` 실행 전 승인 영수증** — 넣지 않는다. 대표 방침은 위임·제한을 두지 않는 것이며, 서버가 어떤 명령이 위험한지 자동 분류하면 오탐으로 정상 작업이 멈춘다. `pc_write`·`pc_move`·`pc_delete`의 기존 승인 receipt 경로는 그대로 두고 `pc_shell`만 위임된 PC에서 바로 실행한다.
- **도구 단위 토큰 권한(scope)** — 넣지 않는다. `padiem_mcp_tokens`는 계정·PC·토큰만 바인딩하고 모든 토큰이 같은 도구 집합을 본다. 도구별 scope를 추가하면 폐기·재발급과 감사에 새 정본이 필요해지므로, 필요 시 별도 결정으로 도입한다.
- **대신 배포 단위의 기능 스위치를 둔다** — `PADIEM_MCP_PC_SHELL_ENABLED`(기본 off, `true`/`1`에서만 켜짐, 그 외 값은 기동 실패). off면 `tools/list`에 `pc_shell`이 노출되지 않고, 이름으로 직접 호출해도 `-32020 tool_not_enabled`로 거부되어 디스패치도 감사 행도 남지 않는다. 게이트는 `mcp_gateway_transport`에 있어 개인 토큰(PAT) 연결과 11절의 OAuth 웹 커넥터 연결이 **같은 스위치**를 지킨다.

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

## 7. OAuth 2.1 설계 메모 (1단계 당시)

1단계 당시에는 개인 Bearer 토큰(PAT)만 있었다. 웹 커넥터에 필요한 항목은 다음과 같았고, 2단계 구현은 11절에 있다.

- Protected Resource Metadata로 `resource`와 authorization server를 알린다.
- Authorization Code + PKCE, 동적 클라이언트 등록(또는 사전 등록), `resource` 파라미터와 audience 바인딩.
- 승인 화면에서 사용자·PC·범위를 확인하고, 발급 토큰은 기존 `padiem_mcp_tokens`/scope 검증에 연결한다.
- 토큰 회전·폐기·감사는 기존 경로를 재사용한다.

Claude Code·Codex처럼 Bearer 헤더를 설정할 수 있는 MCP 클라이언트는 1단계 방식으로 지금도 연결할 수 있다.

## 8. 연결 방법

1. PADIEM 설정의 **외부 AI 연결**에서 연결 이름과 내 PC를 고른다.
2. 개인 토큰을 발급한다. 토큰은 한 번만 표시된다.
3. 클라이언트의 MCP HTTP 설정에 표시된 `/api/mcp` 주소와 `Authorization: Bearer <토큰>`을 넣는다. 토큰을 URL·인자·소스·로그에 남기지 않는다.
4. PC가 연결·승인 상태이고 선택된 실행 PC가 토큰의 PC와 같아야 도구가 실행된다.
5. Claude·ChatGPT 웹 커넥터는 같은 `/api/mcp` 주소를 넣고 OAuth 로그인을 선택한다. 승인 화면에서 PC를 하나 고른다(11절).

## 9. 남은 것

- 장시간 프로세스 `pc_shell_start/read/stop`(위 설계).
- 대용량 출력·파일의 청크/스트리밍 전송.
- Windows·macOS·Linux 셸별 실기기 검증(이번 PC worker 시험은 Windows PowerShell·cmd·Git Bash에서 수행).
- OAuth 클라이언트 관리·DCR rate limit, CIMD, OIDC ID 토큰/워크스페이스 이메일 제한.

## 10. 검증

- `tests/test_mcp_gateway_*.py`, `tests/test_mcp_browser_*_3782.py`, `tests/test_mcp_pc_shell_261103.py`: 129 passed.
- 새 시험 16건: 닫힌 스키마, 위임/연결 거부, 완료·절단·오류·시간 초과, audit 숫자 필드, DB audit 비밀 부재, Windows 실제 worker(PowerShell exit code·stderr·cwd·절단·시간 초과·cmd·bash).
- Windows 기본 인코딩(cp949) 때문에 실패하던 기존 MCP 설정/왕복 시험은 파일 읽기와 자식 `PYTHONIOENCODING`을 UTF-8로 고정해 통과시켰다. 제품 코드 변경이 아니라 시험 환경 수정이다.

참고: DesktopCommanderMCP(MIT). 이 저장소에는 그 소스 코드를 복사하지 않았고, 위에 적은 실행 형태(대기 상한, 출력 상한·절단, 프로세스 트리 종료)만 새 Python/PowerShell 코드로 구현했다. 따라서 `static/third-party-licenses.html`에는 새 항목을 추가하지 않았다. 런타임 의존성도 추가하지 않았다.

## 11. OAuth 2.1 웹 커넥터 (2단계, 2026-11-03)

### 11.1 사양 판과 근거

- MCP Authorization 사양 **2026-07-28**을 기준으로 했다. 이 판은 OAuth 2.1 draft-ietf-oauth-v2-1-13, RFC 6750(Bearer), RFC 8414(AS Metadata), RFC 7591(DCR), RFC 8707(Resource Indicators), RFC 9728(Protected Resource Metadata), RFC 9207(issuer identification)을 참조한다.
  - https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization (2026-11-03 확인)
- OpenAI의 ChatGPT/Codex 커넥터 인증 안내는 보호 리소스 메타데이터, AS 메타데이터(S256, `iss`, `resource`), DCR/CIMD, `resource` 에코를 요구한다.
  - https://developers.openai.com/plugins/build/auth (2026-11-03 확인)
- Claude의 사용자 지정 커넥터는 OAuth 로그인에서 'Claude의 공개 identity(CIMD)', '자동 등록(DCR)', '직접 만든 OAuth 클라이언트'를 선택할 수 있다.
  - https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp (2026-11-03 확인)

### 11.2 (a) Chat 인가 엔드포인트 vs (b) padiem-auth 클라이언트

| 기준 | (a) Chat이 MCP 전용 인가 엔드포인트를 둔다 | (b) padiem-auth에 MCP 클라이언트를 추가한다 |
| --- | --- | --- |
| 사용자 로그인 | 기존 Chat 공통 로그인 세션을 그대로 사용 | padiem-auth 로그인은 같지만 MCP 클라이언트·scope·제품 매핑을 새로 등록 |
| padiem-auth 변경 | 없음 | 코드·허용 목록·배포 변경 필요, 키 재생성 금지 제약과 배포 위험 |
| 토큰 범위 | 기존 MCP 토큰과 같은 owner/PC/scope를 Chat DB에서 바로 발급 | padiem-auth 토큰을 Chat MCP 토큰/PC와 연결하는 교환·매핑이 추가로 필요 |
| 표준 적합성 | AS와 resource server가 같은 origin이어도 허용됨(사양 Roles) | AS 분리는 표준적이나 구현·검증 범위가 큼 |
| 구현 크기 | 작음(기존 token 테이블·PC authority 재사용) | 큼(공통 로그인 권위와 MCP 데이터 권위의 경계 확장) |

**(a)를 선택했다.** 로그인 자체는 계속 padiem-auth 공통 로그인 하나이고, Chat은 그 세션을 확인해 MCP 전용 OAuth 코드·토큰만 발급한다. padiem-auth의 키·클라이언트 설정은 건드리지 않는다. AS와 MCP resource server는 `https://chat.padiem.net` 같은 origin에 있다.

### 11.3 엔드포인트

| 경로 | 역할 |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 보호 리소스 메타데이터. `resource=https://chat.padiem.net/api/mcp`, `authorization_servers=[issuer]`, `scopes_supported=[mcp:pc]` |
| `GET /.well-known/oauth-protected-resource/api/mcp` | 위 문서의 경로별 별칭 |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 AS 메타데이터. issuer, authorize/token/register/revocation endpoint, S256, `iss` 지원, client auth methods |
| `GET /oauth/authorize` | 동의 화면. 요청·client·redirect URI·PKCE를 먼저 검증하고, 로그인 전이면 공통 로그인으로 보낸다 |
| `GET /oauth/authorize/info` | 동의 화면용 JSON(클라이언트 이름, redirect host, scope, 내 PC 목록). 세션 쿠키 전용 |
| `POST /oauth/authorize` | 동의 승인/거절. JSON + 같은 origin. 코드 또는 `access_denied` redirect를 돌려준다 |
| `POST /oauth/register` | RFC 7591 DCR. public(`none`)·confidential(`client_secret_post`/`basic`) 클라이언트 등록 |
| `POST /oauth/token` | authorization_code + PKCE S256 교환, refresh rotation |
| `POST /oauth/revoke` | RFC 7009 액세스/갱신 토큰 폐기 |
| `POST /api/mcp` | 기존 MCP. PAT와 OAuth 액세스 토큰을 모두 받는다 |

401 응답은 다음 challenge를 포함한다.

```
WWW-Authenticate: Bearer realm="padiem-mcp",
  resource_metadata="https://chat.padiem.net/.well-known/oauth-protected-resource",
  scope="mcp:pc"
```

이미 Bearer가 있었는데 거부된 경우 `error="invalid_token"`을 덧붙인다. OAuth 토큰은 `resource`가 이 MCP 서버의 정규 URI와 일치하고 scope가 `mcp:pc`일 때만 `authenticate_mcp_request`를 통과한다. PAT 행은 resource가 NULL이라 기존과 동일하게 동작한다.

### 11.4 클라이언트 등록과 CIMD

- DCR을 구현했다. `redirect_uris`는 정확한 HTTPS URI(로컬 개발은 loopback HTTP)만 받고, fragment·userinfo·비loopback HTTP를 거부한다. `client_name`은 1~100자, `token_endpoint_auth_method`는 `none`·`client_secret_post`·`client_secret_basic`만 받는다. confidential secret은 SHA-256만 저장하고 발급 응답에서 한 번만 돌려준다.
- AS 메타데이터는 `client_id_metadata_document_supported: false`를 명시한다. **CIMD는 이번에 구현하지 않았다.** Claude의 '자동 등록'(DCR)과 ChatGPT의 DCR 경로를 사용한다. Claude의 'Claude의 공개 identity'를 쓰려면 CIMD URL 문서 fetch·검증(SSRF 경계 포함)이 추가로 필요하다.
- DCR은 인증 없이 열려 있다. rate limit·클라이언트 관리 화면은 이번 범위가 아니다. 동의 화면은 클라이언트 이름과 함께 **돌아갈 redirect host**를 보여 주어 사용자가 대상을 확인하게 한다.

### 11.5 로그인 복귀와 동의 화면

- 공통 로그인은 padiem-auth 하나만 쓴다. `/oauth/authorize`가 세션 없는 브라우저를 `/auth/shared/start`로 보낼 때 `__Host-padiem-login-return` 쿠키에 같은 origin의 authorize URL을 넣는다. 공통 로그인 callback의 `issue_session`이 그 쿠키를 읽어 원래 authorize URL로 돌아가고 쿠키를 지운다. 외부 URL·`//`·역슬래시·제어 문자는 `/`로 떨어뜨린다.
- 공통 로그인 흐름이 꺼진 배포에서는 authorize 화면이 로그인 안내와 채트 이동 링크를 보여 준다.
- 동의 화면은 `static/mcp-oauth-consent.html`·`.js`·`.css`이며 문구는 `locale.js`의 ko/en 키를 쓴다. 클라이언트 이름, redirect host, "이 AI가 내 PC에서 파일·명령·브라우저 작업을 할 수 있습니다.", PC 선택, 승인/취소, PC 없음/로그인 필요 상태를 표시한다.
- 승인 POST는 JSON + 정확한 Origin이며, 서버가 client/redirect/PKCE/resource/scope와 선택한 PC가 그 사용자의 것인지 다시 확인한다. 다른 사용자의 PC는 코드를 만들지 않는다.

### 11.6 토큰 저장

- migration **095_mcp_oauth.sql**:
  - `padiem_mcp_tokens`에 `kind(pat|oauth)`, `expires_at`, `refresh_token_sha256`, `refresh_expires_at`, `client_id`, `scope`, `resource` 추가.
  - `padiem_mcp_oauth_clients`(client id/secret hash/name/redirect URIs/auth method) 추가.
  - `padiem_mcp_oauth_codes`(code hash, client, user, device, redirect, PKCE challenge, scope, resource, 만료/소비 시각) 추가.
- 액세스 토큰 1시간, 갱신 토큰 30일. 갱신할 때 액세스·갱신 해시를 같은 행에서 원자적으로 회전하고, 이전 갱신·이전 액세스는 즉시 거부한다. 코드는 10분·1회 소비(조건부 UPDATE)다.
- OAuth 행은 기존 설정의 '발급한 연결'에 `클라이언트 이름 (OAuth)`으로 보이고, 같은 `revoke_token`으로 폐기된다. 계정 삭제는 코드·토큰 행을 지우고, 만료 코드는 정리 회차가 지운다.
- 토큰·코드·secret 원문은 저장·로그에 남기지 않는다. 요청 텔레메트리는 경로·상태만 남긴다.

### 11.7 운영 반영 때 할 일

1. migration 095를 적용한다. 095 전에는 `authenticate`/토큰 발급/갱신 SQL이 실패하므로 MCP 도구가 동작하지 않는다.
2. `PADIEM_CHAT_PUBLIC_BASE_URL`이 실제 HTTPS origin(예: `https://chat.padiem.net`)인지 확인한다. issuer·resource·redirect 검증이 이 값에 묶인다.
3. 공통 로그인(`PADIEM_CHAT_SHARED_LOGIN_ENABLED=true`)이 켜져 있는지 확인한다. padiem-auth 재배포·키 재생성은 하지 않는다.
4. Claude 웹: 사용자 지정 커넥터에서 `/api/mcp` 주소를 넣고 OAuth 로그인을 선택한다. '자동 등록'(DCR)을 사용한다. ChatGPT 웹: 개발자 모드 커넥터에서 같은 주소와 OAuth를 선택한다.
5. 배포 뒤 메타데이터·401 challenge·DCR·승인·토큰·갱신·폐기를 실제 커넥터로 한 번 확인한다. 이 레인은 배포·운영 접속을 하지 않았다.

### 11.8 검증

- OAuth 시험 12건: 메타데이터·401 challenge, DCR 검증/secret, 동의 화면·PC 목록, 전체 PKCE 코드·토큰·갱신 회전·폐기·PAT 회귀, 코드 재사용/오류 verifier/잘못된 redirect, confidential secret, 타 사용자 PC 거부, 만료·다른 resource 거부, 로그인 복귀, ko/en 문구.
- MCP·로그인·삭제·정리·도움말 묶음 **223 passed**(이 기계 최종 광범위 실행).
- padiem-auth 코드·키·클라이언트 설정 변경 없음. 운영 서버 접속·배포·PR 없음.

### 11.9 남은 것

- CIMD 클라이언트 ID 문서, OIDC ID 토큰/JWKS, 워크스페이스 이메일 도메인 제한.
- DCR 클라이언트 관리·rate limit, OAuth 동의 이력 화면.
- 장시간 프로세스와 대용량 전송(1단계 메모의 남은 항목).
