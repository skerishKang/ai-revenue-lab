# 모델 응답시간 제한 원칙: 공급사 조건 우선, 파디엠 자원보호만 유지

**Owner decision 2026-10-12 KST.** Tracking #4448; inventory #4445; implementation #4446, #4442. Source baseline `main 7e1940d7de133832aae89110b30d3367b5938393`.

## 원칙

- **모델이 정상 생성하는 동안 파디엠이 임의로 총 누적 경과시간 30/60/600/900초를 재어 끊지 않는다.** 공급업체/공식 API 중개업체의 이용조건(시간, 토큰, 과금, rate/concurrency 등)과 플랫폼의 실효 제약을 우선 확인한다.
- **무제한 outbound 연결의 완전 해제는 아니다.** 연결은 Worker의 메모리, 동시 연결 수, 스트림 버퍼, provider API 비용 및 사용자의 대기 UX에 영향을 줄 수 있다. 장애/무응답/연결 이탈은 별도의 자원보호 정책과 공정한 admission으로 처리한다.
- 2026-10 Cloudflare Workers HTTP 핸들러는 클라이언트 연결이 유지되는 동안 고정 wall duration 상한이 없지만, 메모리 128MB, CPU 예산, 동시 subrequest 연결 등 자원제약은 존재. 출처: https://developers.cloudflare.com/workers/platform/limits/
- **진행 중인 스트리밍 모델**과 **출력이 없는 stalled model**, **완료형(non-streaming) HTTP 요청**, **도구/코딩 명령**, **인증·보안 TTL**, **CI**는 서로 다른 정책 범주다.

## 전 제품 분류 및 변경 정책

| Source boundary | 기존 기본/상한 | 판단 | 조치 |
|---|---|---|---|
| B14 Provider `b14_timeout_policy.py` + `platform.py` | first header/connect600s; per-chunk read600s | **RESOURCE_IDLE** (누적 모델 실행시간이 아님) | 정상 SSE 진행 중 하드컷 없는 점 유지. 실제 provider 600s 이상 정상 first token 허용 증거가 있으면 안전한 ingress/async architecture 검토 |
| B14 gateway retry/fallback | 후속 재시도 chain 45s; 초기 모델 생성엔 해당하지 않음 | **COST/RETRY** | 유지. 원치 않는 제공자 변경/추가 API 과금 금지 |
| B14 legacy/BYOK | caller budget 기본600s | **UNVERIFIED PROVIDER CONTRACT** | 공급사별 규정 확인, 초기 생성 총 cap인지 idle인지 테스트. 키/계정 공유 금지 |
| AI Core→B14 SSE | caller default600s; 첫 응답/청크 idle 리셋 | **RESOURCE_IDLE** | 정상 진행 중 중단 금지; 실제 브라우저 E2E 필요 |
| AI Core→B14 completed/non-SSE | caller timeout600s; `asyncio.wait_for`도 존재 | **RESOURCE_HELD / TOTAL_WAIT** | 무기한 보장 불가. 가능하면 스트리밍·취소 전파/비동기 작업으로 전환해 총 하드컷 제거, admission과 메모리/비용 통제 후 적용 |
| B62 Chat/Engine model caller | 기본600s, env override 가능 | **MODEL_BOUNDARY + RESOURCE** | 운영 실효값 확인; completed와 SSE를 구분, 600s 총벽이면 스트리밍 우선으로 전환 |
| Core Engine ExecutionContext | 기본900s; 최대3600s | **AGENT_REQUEST / RESOURCE LEASE** | 모델 개별 추론과 혼동 금지. 정상 진행 중 장기 agent의 상태 저장·재개·취소를 점검 후 조정 |
| Engine JS SDK | 명시 `timeout_seconds <=60` (Python+Core<=3600) | **CLIENT_ONLY ARTIFICIAL** | **60→3600 정합화**; 서버가 이미 허용하는 범위만 통과, 허가/실행시간 서버 정책 변경 없음 (#4446) |
| Claw/Kagent 로컬 명령 | 기본120s, 최대900s/kill | **PROCESS_CPU/RAM** | 자원 보호. 장기 빌드/개발 작업은 별도 권한·사용량 정책과 이어하기 마련 |
| Claw 외부 코딩 agent | 기본900/max3600 | **AGENT_RUN RESOURCE** | 공급사·런타임별 프로세스/비동기 job 제약 조사, 모델 토큰 생성과 분리 |
| Living Fiction/Travel/Learning/Personal 모델 | 각 모델 요청 default600s | **NONSTREAMING? PROVIDER + RESOURCE** | 각 모델 adapter가 streaming인지 확인한 후 vendor timeout과 resource metering 비교. 600s total이면 단계적 개선 후보 |
| ToolSpec/P01 외부 작업 | tool max300s, P01 sync transport3600s | **TOOL/WORKER LOAD** | 유지. 장기 작업은 job queue / progress, 멱등 실행 |
| Web/Google OAuth/Drive/Gmail/Slack/calendar/PDF/OCR | 대체로 5–60s | **NETWORK/SECURITY/CPU** | 유지; 해당 도구가 600s 모델 생성이 아니라는 근거 확보 |
| OTP·가입·연결티켓·pairing/retention TTL | OTP300s, connector ticket300s, session/command TTL 별도 | **SECURITY/REPLAY** | 인증·재실행 방지에 반드시 필요, 임의 해제 금지 |
| Desktop IPC/browser open/shutdown | 3s / 30s / 5s | **UI/PROCESS RESOURCE** | 유지. 모델의 응답을 종료하는 데 이 타이머를 재사용하지 않는지 통합 테스트 |
| Portfolio dashboard / Reward external API / GitHub | 대체로 5–28s | **EXTERNAL API + UI** | 유지. 모델 추론 라우팅과 별개 |
| GitHub Actions jobs | timeout-minutes 다수 | **CI/COST** | 유지, 사용자 모델 대기와 별개 |

## 사용량/자원 중심으로 바꿀 때 필요한 안전 장치

1. 서버 부하를 직접 줄이는 **per-user/tenant/provider/model 동시 요청 허가(admission)**, 토큰·과금 예산 및 upstream 429 존중. 무료 회원의 모델 사용 권한과 provider의 무료 사용 계약도 별도로 검증한다.
2. 스트리밍은 백프레셔를 보존하고 요청/응답 메모리 상한을 둔다. completed 응답은 커질 수 있어 **스트리밍 기본 사용 또는 job id+reconnect** 전환 없이 timeout=None으로 만들지 않는다.
3. 사용자가 취소하거나 브라우저 접속이 끊기면 공급사 요청도 취소되거나 명시적 durable job으로 이관해야 한다. orphaned inference/과금 지속 금지.
4. 모델 답변이 계속 생성 중이면 **누적 wall-clock 시간만으로 종료 금지**. 아무 청크도 오지 않는 구간의 idle watchdog는 자원 보호를 위해 별도 유지. 공급사에서 모델이 긴 프리필을 정상 수행하고 증명 가능한 경우 idle 예산 조정/async gateway 도입.
5. 사용자에게 명확히 '모델 제공업체 제한', '파디엠 연결 유휴 종료', '비용·계정 한도', '작업 취소'를 구분해 표시한다. 자동으로 모델을 바꾸거나 재요청하는 방식 금지.
6. 모델별 일괄 timeout보다 **vendor/intermediary 계약 및 메타데이터를 증빙**하고, 알려지지 않은 제약을 무제한/제로 비용으로 간주하지 않는다.

## 현재 완료 범위 / 남은 검증

- 이미 반영된 #4442는 **B14/AI Core 모델 첫 응답 30/55초 제거**; B14, Engine, B62 동일 SHA 배포 PASS.
- #4446 JS SDK는 서버 자체의 리소스 제한을 완화하지 않는 **불필요한 로컬 검증값 변경**. 이 문서와 함께 안전한 작은 PR로 진행한다.
- **나머지 600/900/3600초를 즉시 전부 제거하지 않는다.** completed의 연결 자원 점유, Agent/Tool CPU/RAM, 사용자 취소 전파가 검증되지 않아 오히려 사용자 전체의 품질에 피해 가능. 추후 server-protecting-alternative(스트림/비동기 job + 비용 제어) 구현시 총시간 캡 제거.
- 운영에서 모델 응답 30초 이상, 600초 이상 지속적 청크 출력 및 취소/재개 E2E는 **미입증**. 환경 변수 override를 읽을 정식 권한 필요.
- 이 문서/감사는 공급사 한도 미상과 runtime E2E 미검증을 **UNKNOWN**으로 표기하고 모델별 무제한 동작을 보증하지 않는다.

**Source-policy status: OWNER_POLICY_RECORDED / CLIENT_ARTIFICIAL_LIMIT_PATCHED / ALL_RUN_TIMEOUTS_REMOVED=NO.**
