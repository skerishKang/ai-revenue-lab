# PADIEM MCP Gateway 1차 — 코드 인계

작업 범위: #6460 항목 5 / #4633. 출발점은
`origin/feat/pc-delegation-261101`의
`8850e32bf151d89ff1a66000b5f970b2f8cc29e6`이며, 작업 브랜치는
`feat/mcp-gateway-261101`이다. 사용자 지시는 코드·로컬 시험·push까지다.
PR 생성·머지·운영 반영은 CTO/컴2 레인이 한다.

## 전송과 인증 선택

컴2 Chat의 `POST /api/mcp`에서 JSON 응답을 사용하는 **stateless Streamable
HTTP**를 제공한다. 공식 `2026-07-28`의 `server/discover`, 요청별 `_meta`,
`MCP-Protocol-Version` / `Mcp-Method` / 도구 호출의 `Mcp-Name`, 응답의
`resultType`를 지원한다. 기존 클라이언트용 `2025-11-25`의 `initialize`도
같은 주소에서 지원한다. GET/SSE 연결·서버 세션·자동 재개는 만들지 않는다.
인증된 GET/DELETE/OPTIONS는 405다. `Origin`이 있으면 기존 PADIEM 정본
origin과 비교하고, cookie 없는 외부 클라이언트는 Bearer로만 인증한다.

근거(2026-11-01 확인):

- [공식 전송 규격](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports): 원격 MCP는 한 HTTP 주소로 POST하고 JSON 또는 요청별 SSE로 응답할 수 있다.
- [공식 규격 발표](https://blog.modelcontextprotocol.io/posts/2026-07-28/): 최신판은 연결 초기화·세션 대신 요청별 정보를 사용하고, 기존 HTTP+SSE 전송은 폐기 예정이다.
- [공식 SDK 버전 호환](https://ts.sdk.modelcontextprotocol.io/v2/protocol-versions): modern/legacy 두 wire 계열을 구분한다.
- [공식 인증 규격](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization): HTTP 인증의 표준 OAuth 흐름과 Bearer 사용을 설명한다.

이번 사용자 지시가 허용한 **개인 토큰(PAT)** 방식을 선택했다. 기존 사용자
계정과 연결 PC 한 대를 묶는 자격증명이고, PC 폴더·작업 권한을 새로 부여하지
않는다. DB에는 SHA-256 해시만 저장하고 원문은 발급 응답에서 한 번만 표시한다.
목록·폐기는 기존 로그인 및 same-origin 보호를 쓴다. 요청 때마다 토큰 폐기와
기존 active PC pairing을 다시 확인한다. 신규 배포 비밀·환경변수는 없다.

이는 OAuth discovery/authorization server 구현이 아니다. 수동 Bearer 헤더를
지원하는 MCP 클라이언트를 연결 대상으로 삼는다. ChatGPT 기본 연결 화면의
OAuth 경로 및 각 외부 제품의 실접속 호환은 이 코드 시험으로 입증하지 않았다.
[OpenAI 원격 MCP 안내](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)는
API의 인증값 전달을 설명하며,
[ChatGPT 연결 안내](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)는
별도의 제품 연결 절차다.

기술 선택: 기존 Starlette 라우트, 계정 DB, pairing, canonical identity,
P01 client/bridge, PC driver를 재사용했다. 공식 Python SDK v2도 검토했으나,
현재 Chat 런타임에는 해당 의존성이 없고 이번 범위는 폐쇄된 여섯 도구와
JSON 요청/응답뿐이므로 기존 ASGI 앱에 작은 wire 어댑터를 연결했다.
별도 MCP 서비스·Broker·사용자 DB·권한 엔진을 만들지 않았다.

## 도구와 실행 경로

| MCP 도구 | 인자 | 기존 PC 실행 |
| --- | --- | --- |
| `pc_devices` | (인자 없음) | 소유자의 연결 PC 목록 — 표시 이름·id6·온라인·기본 PC(2026-11-04) |
| `pc_list` | `path`, `device?` | `claw.pc.list_files` |
| `pc_search` | `path`, `query`, `device?` | 같은 목록 도구로 지정 폴더 바로 아래 이름을 문자 검색 |
| `pc_read` | `path`, `device?` | `claw.pc.read_file` — 기존 UTF-8 텍스트 읽기 |
| `pc_write` | `path`, `content`, `device?` | `claw.pc.write_file` |
| `pc_move` | `path`, `destination`, `device?` | `claw.pc.move_file` |
| `pc_delete` | `path`, `device?` | `claw.pc.delete_file` |
| `pc_shell` | `command`, `cwd?`, `shell?`, `wait_seconds?`, `device?` | Claw 공통 background dispatch — 응답 대기 후 같은 작업 ID 반환 |
| `pc_shell_start` | `command`, `cwd?`, `shell?`, `device?` | Claw 공통 작업 즉시 시작 |
| `pc_shell_read` | `job_id`, `offset?`, `length?` (`device?`는 무시) | 공통 상태와 OutputStore 핸들의 범위 읽기 |
| `pc_shell_stop` | `job_id` (`device?`는 무시) | 공통 dispatch 취소 |

사용자·위임·승인 여부를 도구 인자로 받지 않는다(2026-11-04부터 `device` 예외 —
대상 PC 선택만 받으며, 소유 링크·토큰 범위·온라인을 서버가 다시 검증한다).
기기 선택 근거는 `pc_device_links` 단일 원천이고 전체 기기 ID·메시 노드 ID는
응답·로그에 내려가지 않는다(끝 6자 id6만). 경로는 기존 PC root
해석과 grants를 그대로 따른다. 검색은 재귀 전체 디스크 검색이 아니다.
SEND/임의 shell 실행은 2026-11-01 당시 노출 도구에 없었다. 2026-11-03에
네 가지 PC shell 작업 도구를 추가했다. 명령은 기존 위임·기기 경계를 따르며,
실행 전 승인 영수증을 새로 요구하지 않는다. 상세는
`docs/architecture/PADIEM_MCP_DESKTOP_COMMANDER_REPLACEMENT_20261103.md`다.

일반 PC 파일·브라우저 실행은 `mcp_gateway_transport` → `mcp_gateway_dispatch` →
`mcp_gateway_execution.execute_mcp_pc_tool` → 기존 canonical identity / PC
context / Mesh grant → P01/Engine 경로를 따른다. 네 shell 도구는 같은 adapter
검증 뒤 Chat의 Claw 공통 background dispatch로 이어진다. MCP의 정확한 도구를
결정적으로 호출하므로 도구 선택을 위한 추가 B14 모델 호출은 없다.

외부 요청은 사용자 발화로 바꾸지 않으며 `pc_action_context=[]`다. 서버가
검증한 `pc_gateway` 출처를 같은 공통 PC 실행 단계까지 전달한다. 읽기는
기존 권한으로 실행한다. 변경 작업은 이 단계에서 현재 사용자·기기의 저장된
위임 범위를 확인하거나, 아래의 정확한 사용자 승인 기록을 요구한다.
일반 Chat/Claw의 1단계 사용자 발화·인젝션 검사는 그대로 유지한다.

실행 뒤 쓰기(존재·크기·해시), 이동(원본 없음·대상 있음), 삭제(대상 없음·백업
있음)는 2단계 검증을 거친다. MCP 결과도 `completed` / `failed` /
`unavailable`을 실제 검증 결과로 구분하고, 도구 자료에는 지시가 아니라는
표시를 붙인다.

## 사용자 화면 확인과 기록

1. PADIEM 공용 설정의 **외부 AI 연결**에서 연결 이름과 자신의 PC를 선택하고
   토큰을 발급한다. 표시된 `/api/mcp` 주소와 토큰을 클라이언트의 인증 설정에
   넣는다. 토큰을 URL·명령 인자·소스·로그에 넣지 않는다.
2. 위임되지 않은 변경 요청은 도구를 실행하지 않고
   `status: confirmation_required`와 PADIEM 확인 안내를 반환한다.
3. 같은 화면에서 토큰 이름·PC·도구·정확한 경로/목적지/쓰기 내용을 보고
   승인하거나 거절한다. 사용자 결정에는 화면에 표시한 요청 digest가 묶인다.
4. 승인 후 외부 AI에서 **같은 도구와 인자**로 다시 요청한다. 서버가
   사용자·토큰·PC·도구·정확한 인자에 맞는 승인 하나를 원자적으로 소비한다.
   일반 MCP 호출만으로 동작하고 별도 메타데이터는 필수가 아니다.
   `params._meta["net.padiem/approval_id"]`는 정확한 승인 선택이 필요한
   클라이언트의 선택 기능이다. 다른 내용·토큰·사용자·기기의 승인은 쓸 수 없다.
5. 한 승인은 한 번만 소비한다. 승인 유효기간은 새 제품 제한이 아니라 기존
   Core `MAX_APPROVAL_WINDOW`(24시간)를 재사용한다. 응답 유실 시 승인된
   작업을 자동 반복하지 않는다. 재시도 전 PADIEM의 실제 작업 결과를 확인한다.

설정 API는 `/api/account/mcp/tokens`(GET/POST), `/{token_id}`(DELETE),
`/api/account/mcp/approvals`(GET), `/{approval_id}`(POST)다.
저장 위치는 기존 `PADIEM_CHAT_DB`/컴2 SQLite이며,
`085_mcp_gateway.sql`이 credentials/확인 receipt/감사 메타데이터 테이블을
추가한다. `094_mcp_shell_audit.sql`(2026-11-03)은 감사 행에 종료 코드·소요
시간·출력 크기·절단 여부만 추가하며 명령 본문과 출력은 저장하지 않는다.
`100_mcp_token_device_scope.sql`(2026-11-04)은 토큰·승인 코드 행에 기기 범위
(`device_scope`·`device_scope_json`)를 추가한다 — 동의 화면의 "내 PC 전부" 또는
"고른 PC만" 결정이 저장되는 곳이며, NULL은 기존 단일 PC 토큰이다.
기존 PC history run과 `padiem_chat.request`의 `mcp_operation` 로그도 사용한다. 토큰 ID·도구·결과·요청 digest·대상 PC 끝 6자(`device`)를
기록하고 토큰 원문·파일 본문·전체 기기 ID는 로그에 넣지 않는다.

## 반영 및 검증 범위

CTO 머지 뒤 기존 컴2 반영 절차로 같은 코드 세대의 Chat과 P01을 반영하고
기존 DB에 migration 084(위임) 및 085(MCP)를 적용해야 한다. 기존 identity,
admission, PC callback, queue/Connector 설정을 재사용한다. 이 레인은
마이그레이션 실행·배포·workflow_dispatch·실PC 작업을 하지 않았다.

시험은 고정 가짜 토큰 재료, SQLite, 모의 identity/admission/PC 및 실제
프로토콜·bridge·공통 PC 실행 코드를 사용한다. 클라이언트 실접속·실제 Windows
PC·운영 배포 성공을 의미하지 않는다. 검증된 관련 시험은 중복을 빼고 398개다: Chat 118개, 여섯 도구 통합 왕복
2개(modern/legacy), Engine 하네스·검증·위임·gateway 236개, Python SDK 42개.
Engine 229개 회귀 뒤 추가된 gateway 7개는 SDK와 함께 실행한 77개 묶음에서
확인했다. UI pytest에는 실제 출하 JS를 실행하는 Node DOM 14개 시나리오가
포함된다. Python compileall, JS 구문 검사, `git diff --check`도 통과했다.

```bash
# 저장소 루트에서 실행. 모두 로컬 모의 서비스 시험이다.
export PYTHONPATH=apps/padiem-chat:packages/padiem-ai-core:packages/padiem-control-plane:apps/padiem-ai-engine/clients/python:apps/korean-ai-code-agent/src
python -m pytest -q apps/padiem-chat/tests/test_mcp_gateway_*.py apps/padiem-chat/tests/test_pc_delegation_settings.py apps/padiem-chat/tests/test_pc_delegation_settings_ui.py apps/padiem-chat/tests/test_pc_delegation_transport.py
export PYTHONPATH=apps/padiem-ai-engine:packages/padiem-ai-core:packages/padiem-control-plane:apps/korean-ai-code-agent/src:apps/padiem-ai-engine/clients/python
python -m pytest -q apps/padiem-ai-engine/tests/test_mcp_gateway_pc_execution.py apps/padiem-ai-engine/tests/test_pc_delegation_end_to_end.py apps/padiem-ai-engine/tests/test_pc_action_verification_end_to_end.py apps/padiem-ai-engine/tests/test_6460_pc_action_driver.py apps/padiem-ai-engine/tests/test_pc_action_harness.py apps/padiem-ai-engine/tests/test_pc_action_delegation.py apps/padiem-ai-engine/tests/test_pc_delegation_wire.py apps/padiem-ai-engine/tests/test_python_client.py apps/padiem-ai-engine/tests/test_python_client_attachment.py apps/padiem-ai-engine/tests/test_python_client_evidence_only_4469.py apps/padiem-ai-engine/tests/test_python_client_search_judgement_4469.py
```

변경 파일은 이 작업 브랜치에서
`git diff --name-only 8850e32bf151d89ff1a66000b5f970b2f8cc29e6 HEAD`로
확인할 수 있다. Chat의 account/store/transport/dispatch/execution/settings,
Engine 공통 driver와 wire·identity/fingerprint, 공유 provenance parser와
Python client, 해당 시험 및 이 문서가 범위다. `d1_sqlite.py`와
`local_cpython.py`는 수정하지 않는다.

## 추가: pc_shell (2026-11-03)

`pc_shell`과 start/read/stop은 MCP token·계정·기기 검증을 adapter에서 한 뒤
Chat `dispatch_oracle_mesh_command_intent(background=True)`로 실행한다. 작업 ID는
Claw `oracle_mesh_dispatch`의 실제 `dsp_<32hex>`이며 RemoteBackgroundJobs가 공통
상태와 취소를 맡는다. 완료된 원본은 공통 dispatch의 SHA-256·크기를 확인한 뒤
Claw `OutputStore`에 저장하고, `pc_shell_read`는 핸들을 소유자·subject·run·device로
묶어 바이트 범위로 읽는다.

MCP 전용 작업 테이블이나 `%LOCALAPPDATA%\\padiem-mcp-jobs` 파일은 만들지 않는다.
Migration **099_mcp_common_job_receipts.sql**은 기존 `padiem_mcp_audit`에
`job_receipt_sha256`만 추가한다. 원시 job ID·명령·출력은 MCP 감사 DB에 남지 않는다.
계정 삭제는 기존 `padiem_mcp_audit` 사용자 행을 지우고, Queue의
`delete_account_pc_data`는 공통 `oracle_mesh_dispatch` identity를 정리한다.

`PADIEM_MCP_PC_SHELL_ENABLED` 하나가 네 도구를 모두 제어한다. off면 모두
`tools/list`에서 빠지고 직접 호출은 `tool_not_enabled`다. 이미 시작된 해당 토큰의
작업은 stop만 계속 허용한다. `pc_shell.wait_seconds`는 응답 대기값(기본 120·최대
150초)이며 만료되어도 PC 프로세스는 계속 실행된다.

Edge `/api/mcp` 응답 제한은 `MCP_TIMEOUT_MS` 기본 180초다. OAuth API 읽기 30초와
orchestration·답변 생성 60초는 별도 분기 그대로 유지한다. COM2 SQLite
`mesh_device_presence`의 Mesh receipt가 180초보다 오래되면 선택 PC를 offline으로
판정하고 시작을 거부하며 `선택한 PC가 꺼져 있음`으로 답한다. token에 묶인 PC를
다른 online 기기로 자동 변경하지 않는다.

검증은 `test_mcp_pc_shell_261103.py`, `test_mcp_gateway_transport.py`,
`test_mcp_gateway_account.py`, account deletion 및 Mesh presence freshness 시험,
`apps/padiem-chat-front/test/mcp-background-timeout.test.mjs`에 기록한다.

## 추가: MCP OAuth 2.1 웹 커넥터 (2026-11-03)

claude.ai·ChatGPT 웹 사용자 지정 커넥터가 공통 로그인으로 연결되도록 MCP 전용 OAuth 2.1 인가 엔드포인트를 Chat에 추가했다. 사용자 로그인은 기존 공통 로그인 세션 하나만 쓰며 padiem-auth 클라이언트·키는 바꾸지 않는다.

- 메타데이터: `/.well-known/oauth-protected-resource`(+`/api/mcp`), `/.well-known/oauth-authorization-server`
- 인가: `GET/POST /oauth/authorize`, `GET /oauth/authorize/info` (PKCE S256 필수, 동의 화면은 ko/en locale 키)
- 토큰: `POST /oauth/token` (authorization_code·refresh_token 회전), `POST /oauth/revoke`
- 등록: `POST /oauth/register` (DCR public/confidential). CIMD는 이번 범위가 아니며 metadata `client_id_metadata_document_supported=false`로 알린다.
- 401 `WWW-Authenticate`에 `resource_metadata`와 `scope="mcp:pc"`를 넣는다.
- 저장: migration **095_mcp_oauth.sql**. 기존 `padiem_mcp_tokens` 행을 OAuth grant로 확장하고 clients/codes 테이블을 추가한다. 액세스 1시간, 갱신 30일, 코드 10분·1회, 해시만 저장.
- 설정의 '발급한 연결'에서 OAuth 연결을 보고 폐기할 수 있다. 계정 삭제는 코드·토큰을 지우고 만료 코드는 정리 회차가 지운다.
- 배포 전 migration 095와 공통 로그인 활성화, HTTPS public base URL을 확인한다. 상세는 `docs/architecture/PADIEM_MCP_DESKTOP_COMMANDER_REPLACEMENT_20261103.md` 11절.

## 추가: 여러 PC 선택 (2026-11-04, PR #6793 — 컴2로컬1의 실행 컨텍스트 수정과 함께 배포)

한 MCP 연결(토큰)에서 연결된 PC 여러 대를 고를 수 있다. 실행 대상은 **토큰에 묶인 기본 PC 또는 호출마다 고른 PC**이며, Chat 화면에 저장된 PC 선택 preference와는 무관하다(저장 선택은 화면 기본값일 뿐 실행 권한이 아니다 — 컴2로컬1의 실행 컨텍스트 수정 이후 기준).

### 도구

- **`pc_devices`** — 토큰 소유 계정의 연결 PC 목록. 항목: 표시 이름, 기기 ID 끝 6자(id6), 온라인 여부(mesh_device_presence 180초 규칙), 기본 PC 여부. 전체 기기 ID·메시 노드 ID는 응답에 내려가지 않는다.
- **모든 pc_* 도구** — 선택 인자 `device`(표시 이름 또는 id6). 비우면 토큰의 기본 PC(기존 동작 그대로).

### 토큰 기기 범위

OAuth 동의 화면에서 "내 PC 전부"(기본) 또는 "고른 PC만"을 고른다. 결정은 migration **100_mcp_token_device_scope.sql**의 `padiem_mcp_tokens.device_scope`·`device_scope_json`에 기록된다. NULL은 이전에 발급된 단일 PC 토큰 — 토큰의 PC만 허용하며 기존 연결은 무중단이다.

### 안전 규칙 (Desktop Commander 원격 다중 PC 사고 #586·#599 대응)

1. **명시한 device로만 실행한다.** `device`를 명시했는데 그 PC가 꺼져 있으면 `device_offline`, 토큰 범위 밖이면 `device_not_in_token_scope`로 거절한다. 다른 온라인 PC나 기본 PC로 조용히 넘어가지 않는다 — 기본 PC가 온라인인 상태에서도 선택 PC가 오프라인이면 실행하지 않는다. 같은 id6·이름이 여러 대면 `device_ambiguous`로 거절한다.
2. **작업 ID 후속 호출은 그 작업을 만든 PC로 간다.** `pc_shell_start`를 기본이 아닌 PC에서 시작해도, 그 작업 ID의 `pc_shell_read`·`pc_shell_stop`은 그 PC의 작업에 도달한다(호출의 `device`가 달라도 작업 행의 PC가 우선). 다른 사용자·다른 토큰의 작업 ID는 소유권 오류(`이 작업을 확인할 수 없습니다`/`이 작업을 중지할 수 없습니다`)로 거절한다.
3. **거절은 이유 코드와 감사로 남긴다.** `mcp_operation` 로그와 `padiem_mcp_audit` 행에 대상 PC 끝 6자를 남긴다(명령 원문은 기존 digest 규칙 유지).

시험: `tests/test_mcp_multi_device_261104.py` (목록·온라인·기본 PC, 조용한 폴백 금지, 범위 밖 거절, 레거시 단일 PC 토큰, 작업 ID 소유권, 동의 범위 저장, migration 100 멱등).
