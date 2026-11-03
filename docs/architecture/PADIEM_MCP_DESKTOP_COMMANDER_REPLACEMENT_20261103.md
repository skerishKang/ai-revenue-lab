# PADIEM MCP로 Desktop Commander 대체 — 1·2단계

작업일: 2026-11-03  
범위: MCP 게이트웨이·승인·PC 명령 전달, Claw 공통 background jobs, OAuth 2.1 웹 커넥터, 시험·문서.
별도 MCP 작업 실행·저장소와 PC별 MCP 출력 파일은 두지 않는다.

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
| **`pc_shell`** | `command`, `cwd?`, `shell?`, `wait_seconds?` | Claw 공통 background dispatch |
| **`pc_shell_start`** | `command`, `cwd?`, `shell?` | Claw 공통 작업 즉시 시작 |
| **`pc_shell_read`** | `job_id`, `offset?`, `length?` | 공통 상태와 OutputStore 범위 읽기 |
| **`pc_shell_stop`** | `job_id` | 공통 dispatch 취소 |

`shell`은 `powershell`(기본)·`cmd`·`bash`다. `pc_shell.wait_seconds`는 응답 대기값(기본 120·최대 150초)이며 만료되어도 프로세스는 계속 실행된다. 네 도구 모두 닫힌 스키마와 단일 `PADIEM_MCP_PC_SHELL_ENABLED` 스위치를 쓴다.

## 2. pc_shell 동작

1. `mcp_gateway_execution.execute_mcp_pc_tool`이 기존 MCP token/PC/세션 확인을 먼저 수행한다. 토큰의 PC가 연결·승인 상태가 아니거나, 현재 선택된 실행 PC와 다르거나, Mesh grant가 없으면 실행하지 않는다(`chat_pc_target_unavailable`).
2. start와 `pc_shell`은 Chat의 `dispatch_oracle_mesh_command_intent(background=True)`를 호출한다. Claw `RemoteBackgroundJobs`가 공통 `dsp_<32hex>` dispatch의 실행·상태·취소를 관리한다.
3. 사용자 명령과 `cwd`는 UTF-8 Base64로 전달한다. MCP adapter는 token·account·pinned PC·run을 확인하며, 다른 PC로 자동 retarget하지 않는다.
4. 완료된 공통 dispatch 원본은 SHA-256과 바이트 크기를 재검증한 뒤 Claw `OutputStore`에 저장한다. `pc_shell_read`는 소유자·subject·run·device 범위의 핸들을 받아 offset/length 단위로 반환한다.
5. `pc_shell`의 대기 만료는 HTTP 응답만 마친다. 실행 중인 common job을 취소하거나 종료 결과로 바꾸지 않는다. stop은 `cancel_oracle_mesh_dispatches_for_run`으로 해당 job의 고유 run 하나를 취소한다.

## 3. 권한과 승인

- 사전 위임의 단위는 **이 MCP 토큰이 가리키는 연결·승인된 PC**다. 토큰 폐기, PC 연결 해제, Mesh grant 없음, 실행 PC 불일치에서는 실행하지 않는다.
- MCP shell에는 명령별 제한이나 실행 전 승인 영수증을 추가하지 않는다. 사용자가 연결한 PC와 기존 Mesh 실행 grant, 배포 스위치가 경계다.
- `pc_write`·`pc_move`·`pc_delete` 같은 기존 파일 변경 도구는 기존 승인 receipt를 유지한다. 네 shell 도구의 start/read/stop은 해당 token이 소유한 공통 Claw 작업으로만 동작한다.

### 3-1. 이번 단계에서 의도적으로 적용하지 않은 것 (대표 결정 2026-11-03)

- **MCP shell 실행 전 승인 영수증** — 넣지 않는다. 대표 방침은 사용자가 위임한 범위 안의 명령 제한 없이 쓰고, 배포 스위치로만 켜고 끄는 것이다. 기존 파일 변경 도구의 승인 receipt는 유지한다.
- **도구 단위 토큰 권한(scope)** — 넣지 않는다. `padiem_mcp_tokens`는 계정·PC·토큰만 바인딩하고 모든 토큰이 같은 도구 집합을 본다. 도구별 scope를 추가하면 폐기·재발급과 감사에 새 정본이 필요해지므로, 필요 시 별도 결정으로 도입한다.
- **대신 배포 단위의 기능 스위치를 둔다** — `PADIEM_MCP_PC_SHELL_ENABLED`(기본 off, `true`/`1`에서만 켜짐, 그 외 값은 기동 실패). off면 네 도구가 `tools/list`에서 숨고 직접 호출은 `tool_not_enabled`로 거부된다. 진행 중인 해당 토큰 작업의 stop은 계속 허용한다. PAT와 OAuth는 같은 스위치를 따른다.

## 4. 감사

- 기존 `padiem_mcp_audit` 행에 도구 이름·요청 digest·상태·승인 ID를 남긴다.
- `094_mcp_shell_audit.sql`이 `exit_code`, `duration_ms`, `output_bytes`, `output_truncated` nullable 컬럼을 추가한다. 명령 본문과 출력 내용은 저장하지 않는다.
- `099_mcp_common_job_receipts.sql`은 `padiem_mcp_audit.job_receipt_sha256`과 소유자 인덱스만 추가한다. 원시 Claw job ID·명령·출력은 MCP 감사 DB에 넣지 않는다. 계정 삭제의 기존 `padiem_mcp_audit` 정리와 Queue `delete_account_pc_data`의 공통 dispatch 정리를 재사용한다.
- `padiem_chat.request`의 `mcp_operation` 로그에도 같은 숫자 필드만 넣는다. `request_digest`는 해시다. 명령·출력은 로그에 없다.
- 배포 전에 migration 094·099를 적용해야 한다. 요청 감사가 실패하면 실행하지 않으며, 완료 audit에서 receipt를 저장하지 못하면 해당 run의 cancel을 요청한다.

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

장시간 작업은 Claw의 common background path로 연결했다. 새 MCP 테이블·MCP 전용 PC job 파일·PID 파일을 만들지 않는다. `oracle_mesh_dispatch`의 공통 dispatch가 실행 정본이고, Queue `OutputStore`가 완료 출력과 범위 읽기를 제공한다.

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

- Windows·macOS·Linux shell별 실제 PC 검증.
- 대용량 파일의 청크/스트리밍 전송.
- OAuth 클라이언트 관리·DCR rate limit, CIMD, OIDC ID 토큰/워크스페이스 이메일 제한.

## 10. 검증

이번 common-job 구현과 최신 회귀 시험 결과는 이 문서 11.10 및 `docs/operations/MCP_GATEWAY_20261101.md` 11절에 기록한다.

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
6. 앞단 `apps/padiem-chat-front`(Cloudflare Worker)를 재배포한다. `chat.padiem.net`의 실제 진입점이 이 Worker다. OAuth 경로는 원래도 컴2로 넘어갔지만(정적 분기는 최상위 단일 파일과 `/static/`만 잡는다) 기본 8초 마감만 썼고, worker.mjs의 새 판정에서 정적 분기를 명시적으로 피해 `API_READ_TIMEOUT_MS`(30초)를 쓴다. 앞단을 재배포하지 않으면 토큰 발급·인가 호출이 운영에서 여전히 8초에 잘린다.

### 11.8 검증

- OAuth 시험 12건: 메타데이터·401 challenge, DCR 검증/secret, 동의 화면·PC 목록, 전체 PKCE 코드·토큰·갱신 회전·폐기·PAT 회귀, 코드 재사용/오류 verifier/잘못된 redirect, confidential secret, 타 사용자 PC 거부, 만료·다른 resource 거부, 로그인 복귀, ko/en 문구.
- MCP·로그인·삭제·정리·도움말 묶음 **223 passed**(이 기계 최종 광범위 실행).
- 앞단 회귀: `node --test apps/padiem-chat-front/test/*.test.mjs` **65 passed**(OAuth 경로 통과·no-store·TIMEOUT 예산을 다루는 새 시험 7건 포함).
- padiem-auth 코드·키·클라이언트 설정 변경 없음. 운영 서버 접속·배포·PR 없음.

### 11.9 남은 것

- CIMD 클라이언트 ID 문서, OIDC ID 토큰/JWKS, 워크스페이스 이메일 도메인 제한.
- DCR 클라이언트 관리·rate limit, OAuth 동의 이력 화면.

### 11.10 Claw 공통 시간 제한 없는 PC 작업 (2026-11-03)

- 네 도구(`pc_shell`, `pc_shell_start/read/stop`)가 기존 MCP token·계정·기기 adapter 검증 뒤 Claw `RemoteBackgroundJobs`와 공통 `oracle_mesh_dispatch`를 사용한다. 반환되는 `job_id`는 동일한 `dsp_<32hex>` dispatch ID다.
- 완료 출력은 공통 dispatch 원본의 SHA-256·바이트 수를 확인하고 Claw `OutputStore`에 저장한다. 이후 offset/length 읽기는 동일한 소유자·subject·run·device 범위 핸들을 사용한다. 취소는 공통 run 취소 API를 쓴다.
- MCP 작업 테이블·PC별 MCP 작업 파일은 없다. migration **099**은 기존 `padiem_mcp_audit`에 토큰/기기 묶음 `job_receipt_sha256`만 추가한다. 이 행은 기존 account deletion 목록에서 지워지고 common dispatch는 Queue의 `delete_account_pc_data`가 정리한다.
- `PADIEM_MCP_PC_SHELL_ENABLED` off면 네 도구가 모두 숨고 직접 호출은 `tool_not_enabled`다. 단, 이미 시작한 소유 작업의 stop만 허용한다. 사전 실행 확인 영수증은 추가하지 않는다.
- Edge `/api/mcp`는 `MCP_TIMEOUT_MS` 기본 180초이며 OAuth 30초와 orchestration/답변 60초와 분리된다. `pc_shell.wait_seconds` 기본 120·최대 150초는 응답 대기만 제한한다. 실행 프로세스에는 MCP 대기 시간 제한을 전달하지 않는다.
- COM2 SQLite `mesh_device_presence`의 Mesh receipt가 180초를 넘으면 선택 PC를 offline으로 보고 시작을 거부해 `선택한 PC가 꺼져 있음`을 반환한다. MCP token에 묶인 PC 대신 다른 PC를 고르지 않는다.
- 요청 시험은 `test_mcp_pc_shell_261103.py`, `test_mcp_gateway_transport.py`, `test_mcp_gateway_account.py`, `test_account_deletion_261103.py`, `test_5553_mesh_only_presence.py`, `apps/padiem-chat-front/test/mcp-background-timeout.test.mjs`에서 확인한다.
