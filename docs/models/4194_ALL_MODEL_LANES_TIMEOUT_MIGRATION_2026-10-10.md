# #4194 — 전 제품 AI 모델 실행시간 정책 동시 전환

기준 2026-10-10 KST · 대상: `skerishKang/ai-revenue-lab` 전 제품 모델 실제 호출 경로 · 상위 요청: B14만 수정하지 말고 모델이 사용되는 모든 곳을 함께 변경.

관련: [상위 #4194](https://github.com/skerishKang/ai-revenue-lab/issues/4194), [B14×Core #4191](https://github.com/skerishKang/ai-revenue-lab/issues/4191), [배포 증명 #4186](https://github.com/skerishKang/ai-revenue-lab/issues/4186). 본 변경은 소스 전환이며 Production 배포/모델 유료 호출 승인이 아님.

## 1. 기본 정책 및 근거

- **모델 스트리밍:** HTTP 전체 wall-clock 제한과 다음 이벤트 유휴시간을 분리. ZCode처럼 SSE가 계속 진행되는 동안 임의 총 경과시간으로 종료시키지 않는다. 첫 데이터/이벤트 사이 유휴 감시 기준을 **600초**로 설정. 실패·취소·재시도는 별도로 처리.
- **완료형 모델 응답:** 45초 B14 Gateway 상한은 추론 실행을 끊는 타이머로 쓰지 않는다. 첫 수동 또는 자동 라우팅 모델 시도는 upstream idle 감시가 통제한다. B14 45초는 *후속 재시도와 fallback* 창으로만 사용.
- **Core direct HTTPX:** read=600초 (단계 유휴), connect<=30, write<=20, pool<=10. 10초 connect/write 초기 조기 포기 문제를 완화한다. 각 단계 별도이며 합산하지 않는다.
- **Cloudflare Service Binding 완료형:** Sync `B14PostJSONTransport`는 여전히 asyncio 전체 wait_for이고 기본 600초. 이 경계는 스트리밍 유휴타이머와 **같지 않다**. 완료형 600초 이상 생성은 SSE/영속 비동기 작업 경로가 필요.
- **Core ExecutionContext / P01:** 요청의 실행 메타데이터 기본 900초(15분), 허용 1~3600초. 독립적인 모델 호출 idle 600초와 작업 실행 budget 900초를 구분한다. P01 동기 urllib transport는 호환성 위해 3600초로 연장하지만 durable async 작업 관리 필요.
- **Chat·Engine:** 기존 20/50s 클라이언트 모델 제한을 각각 600초 기본으로 변경. Cloudflare Worker Service Binding·JS Fetch 매핑의 실효 runtime 제한은 별도 GET-only 배포 readback이 필요.
- **Living Fiction/Travel/Learning 및 Personal Edition:** 각 모델 호출 기본 read 또는 네트워크 요청 대기를 600초로 확대. Living Travel 최대 설정 3600초. OAuth/웹검색/도구 파서·보안 승인 등 모델 이외 시간 제한은 변경하지 않는다.
- **B14 legacy Provider:** 파일 기반 registry 기본 provider timeout 600초, 최대 3600초. 등록 설정 파일에 명시된 provider별 timeout override는 계속 우선하므로 환경별 실효 값 확인 필요.

**비교 원본:** ZCode `zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f` [stream-idle-timeout.ts](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/stream-idle-timeout.ts), [subagent policy](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/docs/subagent-timeout-policy.md). Codex `stream_idle_timeout_ms=300000` 기본, Claude Code API timeout 기본 600000ms는 서로 다른 영역. 600초는 사용자 작업 안전을 위한 *모델 유휴 출발값*이지 업스트림 공급자 응답 성공 보장이 아니다.

## 2. 대상 호출 그래프 및 동기 수정 파일

| 소유 제품 | 기존 조기 제한 | 변경 소스 | 주의 |
|---|---|---|---|
| B14 gateway | 첫 추론 45초, provider read 40초 | `apps/korean-ai-platform/app/pilot/{gateway.py,b14_timeout_policy.py}` | 추가 fallback/retry 45초 유지 |
| B14 legacy BYOK | 기본 registry 30초, 최대120초 | `apps/korean-ai-platform/app/pilot/{registry.py,config.py,provider.py}` | upstream registry 값 개별 검증 |
| Core model completed & SSE | 모델 read20초, connect/write/pool 10초 | `packages/padiem-ai-core/padiem_ai_core/{b14_execution.py,b14_streaming.py}` | read600, phase30/20/10 |
| Core Service Binding | sync 전체20초 | `.../b14_transport.py` | sync 전체600초, SSE로 확대 필요 |
| Engine | B14 연결50초, run ctx20~60초 | `apps/padiem-ai-engine/{worker.py,app/execution_context_wire.py}`, `.../execution_context.py` | 모델600 / run900, max3600 |
| Chat/B62·B66 quote 재사용 | stream20초, completed50초 | `apps/padiem-chat/app/{config.py,worker_config.py}` | B66 모델 요청도 Chat 호출자 설정 상속 |
| Hark/Claw/P01 | 기본20초, HTTP 네트워크90초 | `apps/korean-ai-code-agent/src/kagent/{p01_adapter.py,p01_run_flow.py}` | ctx900, transport3600 |
| Living Learning | 20초 | `apps/living-learning/app/{ai/padiem_core.py,config.py,factory.py}` | Core client 기본600 |
| Living Travel | 30초, max120초 | `apps/living-travel/app/{config.py,ai/openai_compatible.py}` | 기본600, max3600 |
| Living Fiction | 60초 | `apps/living-fiction/app/ai/openai_compat.py` | read600, phases 30/20/10 |
| Personal Edition | 120초 | `apps/personal-edition/app/{ai/external.py,config.py}` | socket 모델 요청600 |

## 3. 변경하지 않는 것 (모델 추론 실행시간과 목적이 다름)

- 로그인, OAuth, Google Drive, 캘린더, TinyFish/Daum/Firecrawl 웹 검색 등의 연결 실패 탐지 및 외부 서비스 제한.
- E2B/Windows 로컬 프로세스 및 subprocess kill, 도구 실행·승인/샌드박스 lease 만료, 민감 데이터·네트워크 경계.
- 사용자 중단, 이전 요청 취소, quota, 멱등성, 유료 모델 예기치 않은 재시도 방지.
- Kagent external coding runner default 900s/max3600s 및 local runner default120/max900은 **모델 API 연결이 아니라 runner lease 실행 자원 제한**으로 별도 정책 대상. ZCode식 no-fixed-wall + inactivity watchdog은 후속 async-job 도입 전에는 '완료'라고 할 수 없음.

## 4. 운영 및 검증 요구

1. 모델 API 실호출 없이 offline mock으로 **첫 응답 >45초에도 정상 모델 응답**과 stream chunks 사이 유휴 watchdog, 취소, 후속 retry 45초 가드 검증.
2. 테스트의 옛 20/45/50/60 숫자 핀을 새로운 의미에 따라 교체하되, 보안과 quota 테스트는 손대지 않는다.
3. PR exact-head CI GREEN 후에만 source merge, 활성 Production/Secrets 변경은 독립 승인과 readback이 필요.
4. 환경 변수로 옛 20/50/30 값이 존재하면 새 source default보다 우선한다. 각 Worker binding/env/registry 운영 값을 별도로 조회·마이그레이션해야 실제 효력이 있음.
5. 장시간 async 코딩 (>600초 첫 이벤트 공백 또는 >3600초 장기 run)은 영속 작업 ID·SSE heartbeat·모델 의미 단위 복구·cancel/resume·중복 비용 가드가 구현될 때까지 별도 미완료 항목.

## 5. 완료 정의

`source default changed`, `offline tests pass`, `exact-head CI green`, `source merged`, `operational effective confirmed`, `E2E long-running success`를 구별한다. 앞단 문서/PR을 병합해도 운영 승인 없이 마지막 두 단계를 완료라고 기록하지 않는다.
