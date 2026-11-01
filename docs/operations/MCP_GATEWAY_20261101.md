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
| `pc_list` | `path` | `claw.pc.list_files` |
| `pc_search` | `path`, `query` | 같은 목록 도구로 지정 폴더 바로 아래 이름을 문자 검색 |
| `pc_read` | `path` | `claw.pc.read_file` — 기존 UTF-8 텍스트 읽기 |
| `pc_write` | `path`, `content` | `claw.pc.write_file` |
| `pc_move` | `path`, `destination` | `claw.pc.move_file` |
| `pc_delete` | `path` | `claw.pc.delete_file` |

기기·사용자·위임·승인 여부를 도구 인자로 받지 않는다. 경로는 기존 PC root
해석과 grants를 그대로 따른다. 검색은 재귀 전체 디스크 검색이 아니다.
SEND/임의 shell 실행은 노출 도구에 없다.

실행은 `mcp_gateway_transport` → `mcp_gateway_dispatch` →
`mcp_gateway_execution.execute_mcp_pc_tool` → 기존 canonical identity / PC
context / Mesh grant / history run 등록 → 기존 Chat→P01 인증 client →
`ActionGuardedPCQueryStepDriver` → 기존 서명된 Engine→Chat PC callback →
Connector/Mesh로 이어진다. MCP의 정확한 도구를 결정적으로 호출하므로 도구
선택을 위한 추가 B14 모델 호출은 없다. 기존 P01 admission은 그대로 적용된다.

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
추가한다. 기존 PC history run과 `padiem_chat.request`의 `mcp_operation` 로그도 사용한다. 토큰 ID·도구·결과·요청 digest를
기록하고 토큰 원문·파일 본문은 로그에 넣지 않는다.

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
