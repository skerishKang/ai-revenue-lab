# B14 공통 API 전송 시간 정책 — Kira/DeepSeek 실호출 금지

**Issue:** https://github.com/skerishKang/ai-revenue-lab/issues/4186

Date: 2026-10-10. Scope: B14 transport architecture for **all existing model Providers**, using **only offline SenseNova/Inception MockTransport** for this task. No model/paid/quota-bearing API call, token read, Secret mutation or Production deployment.

## 10초가 있었던 이유와 문제

- `platform.py`의 `httpx.AsyncClient`는 원래 **모든 Provider에 connect 10s, read 30s, write 10s, pool 10s**라는 4개의 phase limit을 사용했다. 이 값은 **총 요청 10초 제한이 아니다**. HTTPX read timeout은 전체 생성시간이 아니라 **입력 청크 사이의 대기**다. Kira와 ModelScope에서 경험한 10~11s HTTP504는 추론 품질 실패가 아니라 전송/대기 제한에 의해 발생했다. Kira의 Worker 로그는 `httpx.ConnectTimeout`이라는 **B14 레벨 phase**를 실제로 입증했다. ModelScope의 실패 phase는 과거 안전 로그 누락으로 **미확인**이었다.
- Model별 connect 30s 임시 예외가 추가됐으나, 새 모델이 들어올 때마다 예외를 늘리는 것은 등록 시간을 증가시키며 근본적인 환경 차이를 해결하지 않는다.
- Cloudflare 공식 문서: Python Worker는 Pyodide/WebAssembly 위에서 실행된다. Async `httpx`는 Workers JavaScript **Fetch API**로 변환된다. 패치된 `ConnectTimeout` 이름이 OS/TCP/TLS handshake만 지칭한다고 가정하지 않는다. https://blog.cloudflare.com/python-workers/ ; https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/
- Cloudflare Worker **HTTP invocation의 일반적인 wall-time 하드 제한이 45초는 아니다**. 클라이언트 연결이 유지되면 계속 작업할 수 있다. https://developers.cloudflare.com/workers/platform/limits/
- HTTPX phase timeout 설명: https://www.python-httpx.org/advanced/timeouts/

## 이번 일원화한 설정 (한 파일)

`apps/korean-ai-platform/app/pilot/b14_timeout_policy.py`가 단일 기준이며, `platform.py`의 일반 응답·SSE, `b14_runtime_config.build_http_timeout()`, `gateway.py`의 45s 정책이 모두 여기서 사용된다.

| Scope | Value | Meaning |
| --- | ---: | --- |
| connect | 30s | 모든 B14 등록 Provider의 초기 HTTPX 요청 단계 한도 |
| read | 40s | 응답 chunk 간 대기 한도, **전체 생성시간 아님** |
| write | 20s | 요청 body chunk 전송 대기 한도 |
| pool | 10s | 연결 풀 획득 한도. 매번 새 AsyncClient 생성 정책은 이번에 변경하지 않음 |
| B14 gateway | **45s overall** | 첫 호출과 허용된 **동일 경로 재시도/백오프 전체**를 포함한 asyncio wall ceiling |
| current Engine execution | **60s** | 현재 Core의 `MAX_TIMEOUT_SECONDS`이며, B14 gateway가 15s 여유를 남기도록 원래 설계됨 |

- 위 30+40+20+10은 **순차 합산되는 요청 시간 100초가 아니다**. Phase별 timeout이 먼저 작동하거나, 45s 전체 한도가 먼저 작동하면 중단된다.
- **45s 이상의 비스트리밍 모델 응답**은 현재 제품 경로에서 실패할 수 있다. 이를 해결하려면 Engine/호출자/client timeout contract와 비동기 작업 큐 또는 streaming UX를 설계해야 한다. 단순히 45→120으로 올리면 Engine 60s가 먼저 끊어질 수 있으므로 여기서는 변경하지 않았다. 향후 별도 Owner 검토 대상.
- 재시도 횟수, 자동 fallback, 모델 기본 추론 옵션, Worker auth, Cloudflare Secrets Store metadata, 고객 화면, 신형 Provider 신규 등록 경로는 변경하지 않았다.
- 기존 ModelScope-전용/Kira-전용 30s 예외는 삭제하고 모든 Provider가 동일한 30s connect 정책을 따른다. 벤더별 임의 상수 추가 금지.
- 특정 모델에서 응답 시작이 느리면 error **phase**를 수집하고 공급사 설정과 코딩 도구의 **실제 요청 방식(특히 streaming 여부)**을 비교한다. 시간이 늘었다고 서버 성능이나 응답 정확도가 검증된 것은 아니다.
- 이 변경은 **source-only mitigation, not deployed**이며 Kira 및 DeepSeek API를 시험하거나 호출하지 않는다.

## Focused zero-network validation

Run:
```powershell
cd apps/korean-ai-platform
python -m pytest -q tests/test_b14_shared_timeout_policy.py tests/test_3554_kira_connect_timeout_scope.py tests/test_4176_modelscope_timeout_scope.py tests/test_upstream_retry.py tests/test_alpha1.py::TestResponseLimits::test_timeout_bounds_configured
```

Targeted B14 MockTransport for **SenseNova/Inception**, completed JSON and SSE, verifies exact upstream, no auto retry, safe phase log, current 45s gateway cap, `build_http_timeout()` and both adapters are on one policy. Historical test filenames remain for regression audit but sample Provider test identities are now **non-Kira/non-DeepSeek**. Result initially **29 PASS**. No external model call.

## Precise next gates

1. Exact-head CI GREEN and squash merge source; **do not deploy without explicit Owner approval**.
2. Investigate longer (>45s) user journeys together with Engine/Claw budget owners, **do not silently widen the Engine contract**.
3. If live follow-up is separately approved, choose another Provider such as SenseNova, not Kira/DeepSeek. Ensure its quota/billing consent; use one explicit model, one attempt, no external fallback, sanitized phase logs and no repeated QKR/PDF benchmark.
