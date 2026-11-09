# Chat/Claw 단일 턴 경로 설계 (#7297)

* 상태: 설계 확정 전 (대표 판단 대기) · 목표는 한 개의 턴 실행 경로로 합침
* 범위: 코드 변경 없음 — 이 문서는 방법론만 담는다
* 금지: MiMo 담당 `chat-conversation-module.js`·app.js 대화 구역 수정 (이 문서가 건드리지 않는다)

## 0. 요약

현재 "Chat"과 "Claw"는 화면 표시만 다른 같은 하나의 실행 대상이 아니다 — 서로 다른 **두 개의 턴 실행 경로**로 텍스트를 처리한다. 화면(답변·대화 기록)을 공유하는 DB는 이미 같다. Divergent 되는 지점은 실행 경로뿐이다:

- **Chat 경로** — 브라우저 → `/api/orchestration` 또는 `/api/chat/stream` (B62 direct-B14 lane) → 모델·도구 → `append_exchange` 저장
- **Claw 경로** — 브라우저 → `/api/claw/general` → P01 Engine → ToolRuntime → `append_exchange` 저장 + `claw_run_history` 투영

이름표(Chat/Claw)는 Conversation/메시지 행을 구분하지 않는다. 한 스레드에 대화가 이어지고, 한 쪽에서 보낸 대화가 다른 쪽에서도 그대로 보인다. 양방향 연속은 bereits 검증되어 있다(`apps/padiem-chat/app/history.py`, `chat_` 접두어만).

## 1. 경로 지도 (끝에서 끝)

### 1-A. Chat 경로 — `POST /api/chat/stream` (협약, B62 direct-B14 lane)

| 단계 | 파일:줄 |
|---|---|
| 브라우저 입력창·전송, 제품 결정 | `apps/padiem-chat/static/app.js` (`submitPrompt` ~3632, `PRODUCT_CHAT="chat"` 448) |
| 요청 본문 | `tier`, `custom` 가능 (`app.js:3429-3435`), 첨부(문서·이미지) 바인드 |
| 전송기 선택 (orchestration 우선; 실패 시 /api/chat/stream) | `apps/padiem-chat/static/chat-transport.js` (`requestStreaming` 512) |
| HTTP `POST /api/chat/stream` | `apps/padiem-chat/app/chat_routes.py` (`api_chat_stream` 694) |
| (폴백) HTTP `POST /api/chat` (JSON) | `apps/padiem-chat/app/chat_routes.py` (`api_chat` 1480) |
| 등급·Custom 판정 (모델 선택) | `apps/padiem-chat/app/chat_routes.py` (`_apply_b62_model_policy`, `custom_provider`, 1460s) |
| B14 직접 호출 → 답변 생성·스트리밍 | B14는 별도 서비스; 스트리밍 thought 프레임 (`chat_routes.py:517-518, 1224-1237`) |
| 도구: 웹 검색 | `raw.get("web_search")` (chat_routes.py) |
| 첨부 | 이미지·문서 허용; 이미지 모델 지원 검증 (`chat_routes.py:1512-1523`) |
| Custom (내 키) | 허용, 텍스트만 (`chat_routes.py` custom 파싱, `app.js:3638`) |
| 저장 | `store.append_exchange` → `conversations`, `messages`, scope `PRODUCT_SCOPE_CHAT` (`claw_general_routes.py:468` 공통, `apps/padiem-chat/app/history.py`) |
| 화면 표시 | 같은 `messages` 행을 브라우저가 렌더 |

### 1-B. Claw 경로 — `POST /api/claw/general` (협약, B54 → P01 Engine lane)

| 단계 | 파일:줄 |
|---|---|
| 브라우저 입력창·전송 (같은 화면, 같은 sendArea) | `app.js` (`submitPrompt` — `clawGeneralRequest` 사실, `PRODUCT_CLAW="claw"`) |
| 전송기 | `apps/padiem-chat/static/chat-transport.js` (`requestClawGeneral` 490→503) |
| HTTP `POST /api/claw/general` | `apps/padiem-chat/app/claw_general_routes.py` (`claw_general_execute` 1663) |
| 사전 검증 | `parse_claw_turn_attachments_async` (`claw_attachment_context.py`); **이미지는 거부**(422 `claw_image_attachment_unsupported`, `claw_general_routes.py:1730-1734`); 문서만 통함 |
| Custom 처리 | 있음 — 직접 제공자(`_claw_custom_direct`, `claw_general_routes.py:1755-1787`) — 텍스트만. 단, 라이브 마커·PC 도구 의도와 섞이면 거부 |
| 등급 결정 | `resolve_claw_execution_grade` (`model_policy`), custom 우선 적용 |
| P01 Engine 디스패치 | `P01CoreOrchestrationAdapter` → `P01EngineOrchestrationClient` → `P01_ENGINE_SERVICE` (Service Binding) (`claw_general_routes.py:1-22` 모듈 문서) |
| 도구 실행 | Engine ToolRuntime (PC·파일·앱 조작, desktop op) |
| B14 호출 | Engine → B14 |
| 실행 기록 저장 | `_save_claw_exchange` → `append_exchange` (PRODUCT_SCOPE_CHAT, Chat과 같은 `conversations`/`messages`) |
| 실행 기록/투영 | `project_completed_general_run` → `claw_run_history` (`claw_general_routes.py`) |
| 메모리 제안·승인 UI | `/api/claw/memory*` (`app/claw_memory_routes.py`), UI는 claw workspace 전용 |
| 화면 표시 | 같은 `messages` 행; 캔버스에 추가로 run history·메모리 surface |

### 1-C. 경로별 고유 기능 표

| 기능 | Chat 경로 | Claw 경로 |
|---|---|---|
| 내 키 (Customer Custom) | 사용 가능 (`custom` 필드 트리거) | 사용 가능(서버), **클라이언트에서 거부**(a) |
| 이미지 첨부 | 허용 | 불허(서버) (b) |
| 메모리 검토 표면 | 없음 | 워크벤치 표면 (c) — 단, 서버 API는 owner-scoped 공통 |
| PC 명령 | 인라인 PC 턴 | ToolRuntime + desktop op + 승인 |
| 웹 검색 | 기본(tool id deep_research·explicit_search) | 검색 판단(agent evidence) 포함 |
| 도구 | 소비자 도구(orchestration 봉합) | Engine ToolRuntime (Broker 명령) |
| 스트리밍 | SSE + thought 델타 | SSE(live 이벤트) |
| 생각 요약(thought) | 델타 프레임 | 실행 지표(처리 상태) |
| 첨부 | 문서·이미지 | 문서만 |
| 실행 기록(영수증) | 대화 메시지 자체 | run history 투영(`claw_run_history`) |

### 1-D. 나타났다 사라지는 간단한 축

무엇이 왜 없는지: (a) 클라이언트가 Claw 일반 요청에 `customSelection`을 비워 보내고, 서버는 custom 요청을 직접 추가로 허용하게 돼 있다 — 이미 서버는 custom 처리 경로가 존재(`_claw_custom_direct`), 다만 live·도구 의도와 배타. (b) 이미지 바이트는 서버가 엔진쪽으로 보낼 방법을 못 찾아 거부한다. (c) 메모리 surface가 워크벤치에 종속돼 있다.

## 2. DB 관점

### 2-A. 테이블·필드 차이

- 공용: `conversations` (id, user_id, title, created_at, updated_at), `messages` (id, conversation_id, sequence_number, role, content, created_at) — `apps/padiem-chat/migrations/001_auth_history.sql:17-41`. Chat·Claw가 같은 테이블에 저장된다(`claw_general_routes.py:468` — (`PRODUCT_SCOPE_CHAT`)).
- 스레드 구분은 id prefix(`chat_`, `history.py:569-577`)만 있다. Column product 라벨은 없다.
- Claw 고유: `claw_run_history`(실행 영수증), `claw_coding_conversation_grant`, automation 관련 행 — 실행 영수증은 엔트리 단위로 기록되며 대화 스레드 본질은 아니다.

### 2-B. 이름표 하나로 줄일 수 있는지

이름표가 필요한지는 서버에서 답할 수 있다. 저장 구조는 이미 하나의 테이블만으로 동작하므로 "Chat"·"Claw"는 **DB 라벨이 아니라 실행 경로 라벨**이다. 대화 스레드 자체를 하나로 줄이는 작업은 이미 끝나 있으며(같은 conversations/messages 행), 남은 건 실행 분기 제거뿐이다.

## 3. 추천안 — 합침 방법

### 3-A. 추천: Claw 경로(P01 Engine)를 양쪽 단일 경로로

두 경로 중 P01 Engine이 이미 더 많은 기능을 실행한다(PC·도구·메모리·실행 기록). 거기에 Chat 쪽에서만 있던 기능 세 개를 그대로 들여놓으면 양쪽이 같아진다:

1. **Custom (BYOK) 실행** — P01 route(`claw_general_routes.py`)에 이미 `_claw_custom_direct`가 있고 "텍스트 직접 실행" 경로는 작동한다. 남은 일은 클라이언트가 Claw 일반 요청에도 custom 선택을 보내도록 가드를 여는 것뿐이다 (`app.js:3430`, `app.js:3635`). 양쪽 같아짐 검사: 같은 키·모델 선택을 Chat/Claw 양쪽에서 보낸 답 되기 시험.
2. **이미지 첨부** — P01에서 엔진이 vision content block을 수용하는지가 쟁점이다. 먼저 **문서**가 이미 통하므로, 이미지 바이트를 엔진이 받을 수 있는 컨텐츠 블록 형태로 보내는 서버측 تغییرات이 핵심이다. 양쪽 같아짐 검사: 동일 이미지를 양쪽에서 첨부 + 답변 확인.
3. **기억 화면 (이슈 #7297의 아이템 1)** — 서버는 이미 공통이다(`claw_memory_routes.py`가 `current_user_id`로 owner-scoped, product 차원 없음). 화면 게이트만 그쪽이 하고 있다(`app.js:6615`).
4. **Chat 쪽 폐쇄** — Chat 전용 레인(`api_chat_stream`·`api_chat`)은 이 이관이 끝난 뒤에만 제거한다. 그전까지는 실행 경로는 Engine, 화면 출장면 두 제품 화면은 그대로 유지해 사용자 화면 영향을 최소로.

### 3-B. 대안 (비교)
- Chat 경로를 단일로 하는 안은 P01의 도구를 B62 직접 호출 경로(host)에移植하는 더 큰 구조 변경이다. P01의 도구 런타임·승인·실행 기록을 재현하는 작업량이 더 크다.
- 추천안의 단점: Engine 준비 실패 시 양쪽 모두 실패한다(현재 Chat은 Chat 독립 경로로 동작). 그래서 아래 단계 순서는 Engine이 준비된 뒤 진행하고, 두 경로가 한동안 공존하도록 설계한다.

### 3-C. 단계 PR 순서·되돌리기·시험

| 단계 | 내용 | 되돌리기 | 시험 |
|---|---|---|---|
| S0 | 클로우 custom 연결 (클라이언트 가드만 해제) | 가드 복원 (PR 되돌리기) | 양쪽 동일 키·모델 답변 — 실제 응답 양쪽 일치 |
| S1 | 엔진 이미지 입력 (P01 서버) | 서버측 이미지 임계 후 롤백 | 동일 이미지 양쪽 — Chat과 동일 수준 답변 |
| S2 | 기억 화면 게이트 (Chat에서도 승인 목록·검토 표사) | 게이트 조건 되돌리기 | 양쪽 같은 세션 표시 비교 |
| S3 | Chat 레인 제외 플래그(Engine 단독) | 플래그 역전 | 양쪽 같은 질문 양쪽 동일 답변 + 통계 비교 |
| S4 | Chat 경로 제거 + 이름표 하나로 (제품 표시만 남김) | 제거 커밋 되돌리기 | 전체 test-suite + 화면 회귀 |

화면 영향: S0~S3은 사용자 화면에서 가시적 변화가 없다 (기능 차이는 양쪽에서 동일 기능 목록으로 축소되는 방향). S4에서 두 입력창이 하나의 안내 문구로 합쳐진다 (이름표 차이는 유지).

## 4. 위험

| 위험 | 내용 |
|---|---|
| PC 명령·Claw 에이전트 동작 | 엔진 토폴로지가変わる면 Broker 명령 경로의 승인이 바뀌어 PC 동작이 막힐 수 있다. `dispatch_quota`(`dispatch_quota`) 예약 잔류 트래킹이 영수증과 연결돼 있다. |
| 속도(admission) | P01 엔진은 admission/할당량이 경로별로 다르다. Chat 경로는 admission이 독립적이다. 순간 트래픽이 엔진에 집중할 수 있다. |
| 진행 중인 R5 (MiMo, app.js 대화 구역) | `chat-conversation-module.js`와 app.js 대화 영역은 MiMo 담당이다. S2·S3의 게이트 조건 수정이 해당 영역과 겹칠 수 있다. |
| #7078 (glm6, 세션 검증) | 세션 검증 흐름이 대화 라우팅을 바꿀 수 있다. 환경 검증 커스 частью와 Orchestration 이중화를 확인해야 한다. |
| Memory 제안 영구성 | memory가 PC 턴 제안에 의존한다. 이관 중 제안 표면이 끊기면 첫 턴 승인이 막힐 수 있다. |
| 툴(웹검색) 커버리지 | 웹 검색이 양 경로에 나란히 있는지는 현재 스튜디오로 더 확인이 필요하다 (Chat 경로의 web_search 필드와 P01 증거 판단을 하나로 맞추는 조건). |

## 부록. 근거 (파일:줄)
- 본 문서의 모든 파일:줄은 사용 시점 `main` HEAD 기준으로 적혀 있다. 이후 커밋으로 이동할 수 있다.
- 서버 구현 위치: `apps/padiem-chat/app/chat_routes.py:1480(api_chat)`, `apps/padiem-chat/app/chat_routes.py:694(api_chat_stream)`, `apps/padiem-chat/app/orchestration_routes.py:1347-1350(api_orchestration)`, `apps/padiem-chat/app/claw_general_routes.py:1663(claw_general_execute)`, `apps/padiem-chat/app/claw_routes.py`(Runner 경로), `apps/padiem-chat/app/claw_memory_routes.py`(기억).
