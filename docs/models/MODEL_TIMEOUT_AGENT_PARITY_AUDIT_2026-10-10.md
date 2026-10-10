# PADIEM 전 제품 모델 실행시간 감사와 코딩 에이전트 동등성 기준

> **Issue:** [#4194](https://github.com/skerishKang/ai-revenue-lab/issues/4194) · B14 후속 [#4191](https://github.com/skerishKang/ai-revenue-lab/issues/4191) · 2026-10-10 KST
> **Evidence main:** `9324248e1bb2c80a72b3ed9b62b8554328e4a52e`
> **Audit boundary:** SOURCE/READ-ONLY, no provider API calls, Production/Secrets mutation 0. This is a policy proposal, not deployment approval.

## 1. Executive decision

현재 B14의 45초 전체 호출 제한은 짧은 무료 모델의 실패 후 재시도 문제를 다룰 때 설정된 **내부 정책값**이다. Codex/Claude Code처럼 긴 추론, 도구 호출, 백그라운드 실행을 지원하려는 목적에 맞지 않는다. `45`를 단순히 `120`으로 올리는 것도 정답이 아니다. 별도의 모델 호출/유휴/최초 바이트/실행 작업/도구/권한·연결·취소·과금 예산을 구별하고, 긴 작업의 상태를 HTTP 연결 수명에서 독립시켜야 한다.

**기본 원칙:** 정상 진행 중인 장문·코딩 작업을 짧은 임의 wall timer로 잘라내지 않는다. 단, 연결 실패와 영구 정체를 탐지하고, 취소·도구 종료·중복 호출·사용량 상한은 남긴다. `timeout=None`를 모든 계층에 대입하는 방식은 거부한다.

## 2. 공식 제품 비교: 숫자의 '대상'도 함께 비교

| 확인 대상 | 공식 현재 문서 | 구체적 사실 | PADIEM 적용 해석 |
|---|---|---|---|
| Codex CLI | https://developers.openai.com/codex/config-reference | `model_providers.<id>.stream_idle_timeout_ms=300000` 기본, SSE 재시도 설정 별도 | **5분은 모델 스트림의 유휴 제한**. 한 코딩 작업 전체를 5분에 강제 종료한다는 뜻이 아님 |
| Codex Cloud/API | https://help.openai.com/en/articles/20001545-using-codex-cloud ; https://developers.openai.com/api/docs/guides/background | 여러 단계 도구·검증·수정 작업을 분리된 실행 환경에서 지속; 장기 응답 비동기 시작·조회 | 긴 작업은 progress/job state와 cancel/resume이 주체 |
| Claude Code | https://code.claude.com/docs/en/env-vars | `API_TIMEOUT_MS` 기본 600000(10분); `BASH_MAX_TIMEOUT_MS` 기본 600000(10분); `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` 기본 600000; `CLAUDE_STREAM_IDLE_TIMEOUT_MS`는 명시 시 최소 300000 | 각 **요청·셸 도구·subagent 정체·스트림 유휴**의 시계가 독립적 |

숫자를 동일 종류인 것처럼 직접 대소 비교하거나 공급자의 내부 구현까지 추측하지 않는다. 이 문서는 2026-10-10 조회된 공식 설명을 근거로 한다.

## 3. 소스 감사 범위 및 한계

`git ls-files` 추적 Python/JS/TS/Go/Rust 및 설정 파일 총 **3,231개**에서 tests/docs/generated/fixtures를 제외하고 timeout/deadline + 모델/LLM/AI 라우팅 관련 표현을 조사했다. 시간 제한 표현을 가진 런타임 파일 **306개**, 모델 관련 키워드와 겹친 **123개**를 후속 검토 후보로 도출했다. **자동 휴리스틱**이므로 123개가 실제 inference timeout이라고 단정하지 않는다. 제품 내부에서 모델 호출을 우회·전달하는 경우도 있으므로 단순 파일명 검색으로 완전한 호출 그래프를 인증하지 않는다.

| 그룹 | timeout과 모델 관련 표현이 겹친 파일 | 주요 지점 |
|---|---:|---|
| `packages/padiem-ai-core` | 29 | `execution_context.py`, `b14_execution.py`, `b14_streaming.py`, `b14_transport.py`, `orchestration.py`, `tool_resource_policy.py` |
| `apps/padiem-ai-engine` | 27 | `worker.py`, `execution_context_wire.py`, `tool_execution_service.py` |
| `apps/korean-ai-platform` | 21 | `b14_timeout_policy.py`, `gateway.py`, `platform.py`, `provider.py`, `registry.py` |
| `apps/korean-ai-code-agent` | 18 | `p01_adapter.py`, `p01_run_flow.py`, `external_coding_agent.py`, `local_agent.py`, document/OCR isolation |
| `apps/padiem-chat` | 12 | `config.py`, `b14_client.py`, `worker.py`, `httpx_compat.py` |
| `apps/personal-edition` | 4 | `app/ai/external.py` |
| `apps/living-learning` | 3 | `app/ai/padiem_core.py` |
| `apps/living-travel` | 3 | `app/config.py`, `app/ai/openai_compatible.py` |
| 기타 | 6 | reference, scripts, QA 등; 실제 모델 전송 여부 미확인 |

추가 표본 검증으로 `apps/living-fiction/app/ai/openai_compat.py`의 timeout 60초를 확인했다. `apps/b66-sol61-multipage/sol61_multipage.py`는 자체 모델 추론을 실행하지 않는다고 명시하며, B66의 견적 해석은 `apps/padiem-chat/app/b14_client.py` 경계 및 Service Binding을 재사용한다. **B66 견적 렌더러·PDF 생성의 작업 제한과 모델 호출 제한을 혼동하지 않는다.**

## 4. 확인된 값과 실제 의미 (source default ≠ production effective)

| 구간 | 코드 및 설정 | 소스 기본 또는 최대 | 제한 종류/특이점 |
|---|---|---|---|
| B14 Alpha 완료형 | `app/pilot/gateway.py` | **45초** | 요청 전체 retry/fallback wall limit. #4187 merge 이후에도 유지 |
| B14 → 등록 Provider | `app/pilot/b14_timeout_policy.py` | connect30/read40/write20/pool10 | HTTPX 단계별. 각각을 합산하지 않음 |
| B14 legacy BYOK | `app/pilot/provider.py`, `registry.py` | default 30 / registry 최대120 | Alpha와 다른 호출 경로/정책 |
| Core → B14 완료형 | `padiem_ai_core/b14_execution.py` | 설정 default20/max60; connect/write/pool 최대10 | HTTPX 단계별 + caller가 제공한 전체? 추가 확인 |
| Core → B14 스트림 | `padiem_ai_core/b14_streaming.py` | 위와 동일한 phase 설정 | HTTPX read는 보통 chunk idle. Worker binding semantics 별도 검증 |
| Core Service Binding Bridge | `padiem_ai_core/b14_transport.py` | default20, caller override 최대60 | `asyncio.wait_for()`는 **진짜 전체 호출 시간 제한** |
| B62 Chat | `apps/padiem-chat/app/config.py` | stream20, completed50 | 모델 UI/Service Binding 매핑 따라 동작 구분 필수 |
| B62 Chat actual Worker | `apps/padiem-chat/worker.py` | Service Binding 선택 | B14 completed/stream은 `CloudflareB14ServiceTransport`/`CloudflareB14StreamingServiceTransport` 우선 |
| Chat Worker JS Fetch compat | `apps/padiem-chat/app/httpx_compat.py` | supplied `timeout` | **Fetch 직접 호출일 때** `AbortSignal.timeout`이 total request/body deadline. Service Binding과 동일하지 않음 |
| Chat external web HTTP | `apps/padiem-chat/worker.py` `CloudflareExternalHttpTransport` | Core web request `read` 사용 | read phase값을 Fetch **total AbortSignal**로 변환. AI 응답 제한과 웹 검색 제한을 혼동 금지 |
| Engine B14 outbound | `apps/padiem-ai-engine/worker.py` | 50초 | Engine B14 transport config; context wall과 독립 |
| Engine Context | `padiem_ai_core/execution_context.py` | 기본20 / 최대60 | 전체 run budget; 연속 도구 실행에 짧을 수 있음 |
| Core ToolResourcePolicy | `padiem_ai_core/tool_resource_policy.py` | 기본 최대300초 | 도구별 실행 safety policy. **일괄 삭제 금지** |
| Kagent P01 factory | `apps/korean-ai-code-agent/src/kagent/p01_adapter.py` | 기본20초 | Engine context로 직렬화, Core 최대60의 영향을 받음 |
| Kagent P01 network | `.../p01_run_flow.py` | 90초 | socket HTTP transport 상한(작업 전체 한도 아님) |
| Kagent external coding runner | `.../external_coding_agent.py` | 기본900 / 최대3600초 | external run 계약; P01 단일 실행과 작업 수명 관계 확인 |
| Kagent local runner | `.../local_agent.py` | 기본120 / 최대900초 | local run별 계약 |
| Living Fiction | `apps/living-fiction/app/ai/openai_compat.py` | 60초 | 외부 모델 어댑터 모든 HTTPX phase |
| Living Travel | `apps/living-travel/app/config.py` | 기본30 / 최대120초 | AI provider request |
| Personal Edition | `apps/personal-edition/app/ai/external.py` | 기본120초 | 외부 AI socket request |
| Living Learning | `apps/living-learning/app/ai/padiem_core.py` | 기본20초 | Core context 호출 |

모든 값은 **source**이며 활성 배포의 Cloudflare Worker 버전, env overrides, Runtime/Service Binding 구성은 별도 GET-only readback이 필요하다. B14 #4186은 source 병합 완료/운영 배포 승인 대기로 분리한다.

## 5. 원인 및 변경 정책

### P0 — 모델 추론을 중단시키는 조기 wall limit

- B14 Alpha 45초 cap은 엔진 최대60초 안에 기존 retry를 끝내려는 가정에서 탄생했다. 긴 추론·코딩 단일 요청에 무조건 적용하지 않는다.
- **제안:** 모델 completed HTTP 호출의 단기 처리와 long-running model generation을 구분한다. 긴 요청은 SSE event/first-byte/idle 구분 또는 durable async job을 제공한다.
- 신규 synchronous 정책 수치는 공식 경쟁사 수치를 그대로 붙이지 않고 오프라인 simulated 0/20/40/45/50/60/300초 event schedule, caller budget 전달·예산 만료 상태로 결정한다.

### P0 — Chat/Engine/P01 실행 컨텍스트 20~60초와 15~60분 코딩 계약 충돌

- 하나의 `ExecutionContext.timeout_seconds`를 다중 단계 작업 수명과 동일시하면 설계 충돌. **에이전트 run**과 **개별 model call**을 분리한다.
- 도구 승인으로 대기 중인 구간, 사용자 입력 대기, 자원 점유 중인 실제 계산 구간은 별도 상태로 노출. 장시간 run에는 `run_id/status/progress/heartbeat/cancel/resume` 기반 전환 검토.
- 기존 external coding agent 900/3600, local 120/900은 단독 계약 값이다. 실제 서비스 경로가 해당 제한을 어떻게 적용하는지 입증 전 동작 보장 단정 금지.

### P1 — 작은 연결 단계와 보안상 유지할 제한

- Core 10초 connect/write/pool은 느린 전송 상황에서 별도 조기 실패 가능. phase의 실제 서비스 바인딩/Fetch 경로 확인 후 통일.
- DNS/TLS/connection, waiting pool, malformed JSON, 크기 제한, 업로드·OCR·로컬 parser subprocess kill, OAuth/connector 네트워크, tool sandbox TTL, user cancellation, quota/paid calls safeguards는 inference wall cap과 목적이 달라 **유지/개별 개선**.
- 504/502/429를 하나의 '느림' 원인으로 뭉개지 않고 timeout phase, first byte, idle, upstream server, client cancel을 별도 태깅한다.

## 6. 변경 전 검증 계약

1. Codex·Claude의 공식 기준대로 `model request`, `model stream idle`, `agent job wall`, `tool command`, `tool/connector net`을 분리하여 소유 팀을 지정.
2. B14 Alpha·legacy BYOK·Core direct HTTP·Chat/Engine B14 Service Binding·P01·B66 quote 경로의 **효과적 제한**을 end-to-end 표로 증명(운영 적용 읽기 전용).
3. 결정적 MockTransport/fake clock: 첫 데이터 55초 후 정상 완료, 5분 간격 미응답과 chunk-progress, 사용자 취소, 동일 요청 idempotency, retry/fallback 과금 방지. 모든 실 upstream POST 0.
4. B14 우선 수정, Core/Engine/Kagent/B62/B66 변경은 해당 담당 팀과 PR 분리. exact-head scoped CI 통과 후 source merge, 운영 배포와 실제 API 검증은 각기 별도 사용자 승인.
5. 장시간 작업의 승인·재개·사용량·비용·고아 프로세스 방지 조건이 입증되기 전 `timeout=None`의 무제한 호출은 채택하지 않음.

## 7. 작업 분할과 추적

- [#4194](https://github.com/skerishKang/ai-revenue-lab/issues/4194): 전 제품 아키텍처·정책 (본 보고)
- [#4191](https://github.com/skerishKang/ai-revenue-lab/issues/4191): B14×Core phase/호출자 예산 감사
- [#4186](https://github.com/skerishKang/ai-revenue-lab/issues/4186), [PR #4187](https://github.com/skerishKang/ai-revenue-lab/pull/4187): B14 transport phase source-only 개선; **운영 배포 대기**
- [#1990](https://github.com/skerishKang/ai-revenue-lab/issues/1990), [#2544](https://github.com/skerishKang/ai-revenue-lab/issues/2544): 과거 Engine B14 50초 / Chat completed 50초 조정 완료; 중복 수정 금지.

**Safety:** Kira/DeepSeek model real calls 금지. 다른 유료 모델 호출도 별도 승인 없이는 금지. Secrets/Production/외부 고객 데이터 변경 금지.
