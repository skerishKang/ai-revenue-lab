# PADIEM 전 제품 시간제한·만료·취소 정책 전수감사

- 기준일: **2026-10-12 KST**
- Source authority: `skerishKang/ai-revenue-lab` **main `80991a7d0da4bec9d887ca5158c61205ac94f96f`**, PR #4444 이후 상태
- 추적: [#4445](https://github.com/skerishKang/ai-revenue-lab/issues/4445); 모델 조기 종료 [#4442](https://github.com/skerishKang/ai-revenue-lab/issues/4442); Engine JS SDK 불일치 [#4446](https://github.com/skerishKang/ai-revenue-lab/issues/4446)
- 방법: 전체 Git 추적 파일 5,847개 중 Python·JS/TS·HTML·CSS·YAML·TOML·JSON·SQL·셸 등 코드/설정 4,348개 파일 전문에 대해 `timeout/time limit/deadline/idle/watchdog/TTL/expire/AbortSignal/setTimeout/wait_for/Retry-After/duration` 정적 검색. **해당 문자열이 코드에 없거나 동적 외부 플랫폼/운영 환경변수로만 적용된 시간제한은 전수증명 대상 밖**이다.
- 결과: **1,744개 파일 / 11,953개 일치 줄**: 운영코드로 분류된 4,683줄, 테스트 5,620줄, CI 1,411줄, 스크립트 173줄, 설정 50줄, 문서 내 코드 14줄, 운영 2줄. 이는 **서로 다른 timeout 11,953개라는 뜻이 아니다**. browser smoke·sample·구 reference 코드도 자동 분류되므로 운영 서비스 여부는 아래처럼 따로 확인한다.
- 재현 가능한 검색 원자료(운영 PC): `G:\padiem-timeout-audit-20261012\all_hits.csv` (1.77MB; 파일·줄번호·코드 일부·그룹·분류), `summary.json`. 키·인증정보·고객 메시지 본문은 포함하지 않음. 원자료는 repo 안으로 복제하지 않아 운영 소스와 CI에 영향을 주지 않음.

## 1. 전체 제품군·레이어 정적 검색 분포

다음 숫자는 **runtime으로 분류된 패턴 일치 줄 수**이며 모델 요청 경로 수, 보안 사고 건수, 배포 제품 수와 다르다.

| 구역 | 일치 줄 | 의미 / 대표 타이머 |
|---|---:|---|
| `apps/korean-ai-code-agent` (Claw/Kagent) | 1,377 | 로컬 명령·코딩 러너, 샌드박스, OCR/문서 parser, 브로커 폴링, OAuth/Gmail |
| `packages/padiem-control-plane` | 560 | OTP·세션·pairing challenge·커맨드 lease·OAuth·retention TTL |
| `apps/padiem-chat` (B62/B66/Claw UI) | 535 | 채팅 model completed/SSE, Worker Service Binding, 웹검색·인증, 브라우저 상태 |
| `apps/padiem-ai-engine` (P01/Engine/Hark) | 466 | B14 모델 budget, ToolSpec, 외부 드라이브·캘린더·이메일, 작업 재개 |
| `packages/padiem-ai-core` | 402 | B14 HTTPX, orchestration context, Agent inactivity, 웹검색·ToolSpec |
| `reference/*` | 246 | B66/B67 등 예전 화면·PDF worker·샘플 타이머; 실제 배포 여부 구분 |
| `apps/padiem-desktop-shell` | 189 | resident IPC, browser-open, runner 종료 grace, 프로세스 supervision |
| `apps/korean-ai-platform` (B14) | 182 | Provider model first-response, retry/fallback, timeout diagnostics |
| `apps/portfolio-console` | 181 | GitHub API/GraphQL fetch, stale refresh, dashboard·프론트 UI |
| `apps/living-fiction` | 145 | 직접 모델 API 600s, 인증/토큰 유효기간 |
| `apps/personal-edition` | 121 | 모델 생성 600s, 도메인 idempotency/결과 보존 |
| `apps/living-travel` | 108 | 모델 API 600s, 외부 데이터/예약 서비스 |
| `apps/personal-video-archive` | 75 | 미디어·보관·외부 작업 시간제한 (모델 경로 여부 별도) |
| `apps/living-learning` | 43 | Padiem Core 모델 600s, lease/idempotency |
| `apps/ai-reward-router` | 39 | 외부 적립/제휴 어댑터 요청 기본 5s |
| `packages/padiem-embedded-runtime` | 7 | 호스트 런타임 경계/짧은 정책 |
| `tools/*` | 5 | 개발 보조 |
| `apps/padiem-lab` | 2 | 소량의 시간 관련 코드 |
| `.github/workflows` (별도 CI) | — | **174개 workflow yml**에서 `timeout-minutes:` **357개 줄**; 사용자 모델 응답 제한 아님 |

## 2. 실제 시간을 끊는 모델·Agent 실행 경로

| 계층 / 소스 | 현재 source 기본값 | 의미 | 판정 |
|---|---|---|---|
| B14 `app/pilot/b14_timeout_policy.py` | `CONNECT_SECONDS=READ_SECONDS=600`; write20, pool10 | Provider 첫 응답 및 청크 유휴 예산 | **30s/55s 모델별 제한 제거 확인** |
| B14 `app/pilot/gateway.py` | `GATEWAY_WALL_SECONDS=45` | **첫 생성 시도가 아닌** 추가 retry/fallback chain 예산 | **유지/관측**: 기본 retry=0 및 exact route 확인 |
| B14 `app/pilot/provider.py` (legacy/BYOK) | connect/read = `resolved_timeout`, 기본 600 | 기존 모델 호출 | **정합** |
| Core `b14_execution.py` | model timeout 기본600, 범위1–3600; connect/read 동기화 | completed형 B14 호출 | **정합**; 완료형 전체 caller deadline은 별도 |
| Core `b14_streaming.py` | first response 및 **청크별 idle=600** | SSE 이벤트 정상 진행 시 타이머 갱신 | **정합**; >600s 실제 E2E 미검증 |
| Core `b14_transport.py` | `asyncio.wait_for` 기본600 | 비스트리밍 POST 예산 | 호출형태상 **의도된 총 예산** |
| B62 `app/config.py`, `app/worker_config.py` | model stream/completed 600 | 브라우저→Worker→B14 기본 모델 대기 | **기본값 정합**, 운영 변수 override readback 필요 |
| Engine `worker.py` | Engine→B14 기본600; 웹검색 타이머 별도 | B14 model lane | **기본값 정합**, 운영 override 확인 필요 |
| Engine `app/execution_context_wire.py` / Core `execution_context.py` | execution context 기본900, 허용 최대3600 | 단일 Engine request context 예산 | **모델 600과 구분** |
| Core `agent_definition.py` / `agent_progress.py` | Agent 진행/유휴 watchdog, default900; cumulative max_total 없음 | 진행 중인 Agent 전체 누적 wall이 아님 | **유지**, runtime cancel/resume 증거는 별도 |
| Kagent `local_agent.py` + `windows_local_executor.py` | **개별 명령 기본120, 최대900초**; `process.wait(timeout=...)` | 로컬 명령/빌드 프로세스 **실제 hard kill 가능** | **장시간 코딩 UX 검토**; 모델 API 호출과 다름 |
| Kagent `external_coding_agent.py` | 코딩 러너 요청 기본900, 최대3600 | 외부 코딩 세션 실행 계약 | **장기 Agent과 계약 정합성 확인** |
| Kagent `p01_run_flow.py` | 전송 예산3600 | 장기 P01 동기 호출 호환 | 유지; 비동기 재개 설계 별도 |
| Core `tool_resource_policy.py` | ToolSpec timeout ceiling300 | 모델 호출 아닌 단위 도구 실행 상한 | **유지**, 과도한 Tool 사용 여부만 점검 |
| Living Fiction/Travel/Learning/Personal | 각 AI provider 기본600 | 직접 모델 API 대기 | 소스 정합, 제품별 runtime override/실제 응답 미검증 |

## 3. 모델 생성과 구분해야 하는 단기 I/O·보안 제한

| 기능 | 대표 값·소스 | 왜 곧바로 제거하면 안 되는가 |
|---|---|---|
| B62·Core 외부 웹검색 | 기본15s, web max30; `padiem-chat/app/config.py`, Core `web_runtime.py` | 일반 웹 응답 정지 감지, 공급사 모델 추론과 별개 |
| B62 로그인/커넥터 요청 | `auth.py` 15s/connect8; `connector_ticket_routes.py` 15s | 인증 요청 리소스 보호 |
| Gmail/Drive/Slack 및 Engine 일정·메일 | Core capability 30s, Engine connector lease 1–60s | 외부 SaaS read/write·권한 제어 |
| 제어계층/사용자 안전 | OTP TTL300s, connector ticket 최대300s, local session 최대3600s, command TTL 최대900s, pairing challenge 30–600s | 인증 재사용/권한 만료·재실행 경계; **연장 시 보안 영향** |
| 장기 연결 자격 | local pairing credential TTL 최대2,592,000s(30일) | 인증키 수명, 모델 응답 시간이 아님 |
| 저장/자료 보존 | retention TTL 최대31,536,000s(365일) | 개인정보·삭제 정책 |
| Kagent E2B | HTTP transport30s, sandbox default300s | provisioning HTTP vs sandbox session life; 코딩 모델 자체의 first token 아님 |
| Kagent parser/OCR | 별도 자식 프로세스 hard timeout30s 등 | 악성/정지 PDF·이미지 처리 자원 회수 |
| Desktop shell | resident IPC3s, browser open30s, runner 종료 grace5s | UI 연결·프로세스 종료 보호 (건강한 코딩 모델 요청 아님) |
| 포트폴리오 콘솔 | GitHub API request12s, stale refresh6s, 전체 sync24s/handler28s | 관리 대시보드 상태 동기화; AI 토큰 생성시간 아님 |
| AI Reward Router | 외부 adapter default5s | 제휴 API 네트워크 보호 |
| 레거시 B66 PDF/reference | PDF worker 준비5s/파싱10s, 인쇄 미리보기 cleanup5분 | PDF 처리·임시 자원 정리. 대용량 PDF 품질은 별도 시험 |
| CI | `timeout-minutes:` 357곳 | 빌드·배포 러너 비용/교착 방지, 서비스 응답 timeout과 별개 |
| 테스트/브라우저 animation | playwright wait, setTimeout, debounce 등 | 테스트 동기화/애니메이션; 운영 추론 상한과 별개 |

### 검증이 필요한 fetch 구현의 구분

- B62 `worker.py`에 `AbortSignal.timeout(read)`가 있지만 **외부 Web/Connector fetch용 transport**에 사용된다. B14 SSE 모델 호출은 `CloudflareB14StreamingServiceTransport`를 Service Binding으로 주입하고 Core streaming layer가 이벤트별 idle watchdog를 담당한다.
- Engine `cloudflare_external_transport.py`는 **허용된 외부 GET/web 작업**이며 Worker Fetch 한 번에 대한 제한을 부여한다. 이것만 보고 실제 B14 모델 스트림이 600초 누적 시 무조건 끊긴다고 결론 내리면 안 된다.
- 브라우저 `static/app.js`의 `AbortController` 존재만으로 30초 모델 하드컷 증거가 되지 않는다. cancel/user stop 신호와 timer의 연결을 각각 검사해야 한다.

## 4. 수정·추적 우선순위

**P1 — 계약 불일치 (코드 증거 확보)**
- [#4446](https://github.com/skerishKang/ai-revenue-lab/issues/4446): Engine **JS SDK `execution_context.timeout_seconds <=60`** vs Python SDK/Core `<=3600`, Engine server default900. JS에서 900/3600 요청 시 서버에 가기도 전에 실패한다. 현재 repository 검색상 직접 JS SDK import는 주로 SDK 테스트에서 발견됐으며, 운영 브라우저 SDK의 실제 사용 여부 확인 전 사용자 실장애로 단정하지 않는다.
- 추가 작업: JS SDK 배포 사용처 + API 버전별 상한 교차 검증 → 범위 정합화 + 60/61/900/3600/3601 테스트.

**P1 — 전 제품 운영 진실성 (증거 부족)**
- [#4442](https://github.com/skerishKang/ai-revenue-lab/issues/4442): 소스/CI 및 B14·B62·Engine 배포는 같은 SHA로 성공했지만, **인가된 브라우저/Claw→Engine→B14의 >30초 모델 SSE, >600초 진행/청크 리셋, 취소/재개와 배포 환경변수 override**는 실사용 증명 미완료. 운영 E2E 후 종료 판단.
- Cloudflare secret 값은 읽지 않는다. 정식 관리자 경로의 숫자형 공개 가능 metadata 또는 boolean override presence만 조회해야 한다.

**P2 — 코딩 Agent 실행 범위**
- `local_agent.py` 기본120/최대900초 명령 timeout, `external_coding_agent.py` 기본900/최대3600초 계약, E2B sandbox300초를 **장기 진행 Agent의 무제한 누적 실행과 혼동하지 않고** 작업 단위·자동 재개·명시적 취소 UX 측면에서 테스트. 명령을 무작정 무기한 실행하게 만들면 runaway 비용/권한 사고 위험.
- PDF/OCR parser 30s, B66 PDF parser 5/10s는 실제 고객 대용량 문서의 timeout 재현 시 조정하며 기본 보호 유지.

**보존 (보안·운영 안전)**
- OTP/로그인/권한 티켓/승인 lease, OAuth, 네트워크 검색, 바인딩 장애 감지, 프로세스 kill/grace, CI job timeout을 모델 인퍼런스와 구별한다.
- Agnes upstream HTTP429는 timeout 일괄 수정으로 해결되지 않는다: [#4441](https://github.com/skerishKang/ai-revenue-lab/issues/4441).

## 5. 재현·추가 완료 조건

1. 저장소 전체에서 `timeout|deadline|idle|watchdog|ttl|expire|AbortSignal|setTimeout|wait_for|timeout-minutes`를 검색하여 file+line+scope를 수집한다. 원자료는 위 `G:\padiem-timeout-audit-20261012\all_hits.csv` (최신 SHA 고정).
2. 경계마다 **모델(first response / completed / SSE idle), 장기 Agent 누적/진행, 단일 Tool/코딩 명령, 보안 TTL, 외부 Web/OAuth, UI UX, CI**를 분류하고, 오탐(과거 문서·모의 테스트)을 제외한다.
3. 컴파일된 Python/JS SDK 교차 정합 검증과, 허가된 실제 고객 브라우저 모델 장시간 E2E를 분리한다.
4. 건강한 스트리밍이 계속되는 동안의 누적 시간과, 실제 600초 유휴(청크 부재), 사용자 취소, 인증 만료, 승인 중단은 각각 별도 결과여야 한다.
5. 현재 문서는 **SOURCE_AUDIT_COMPLETED / PRODUCT_RUNTIME_TIMEOUT_CONSISTENCY_NOT_YET_PROVEN** 상태. 모든 11,953개 일치 줄의 실행 검증이나 실제 운영 secret/env 동등성이 완료됐다는 뜻이 아니다.
