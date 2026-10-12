# PADIEM 모델 응답 대기·유휴 제한 전 제품 정합화 — 2026-10-12

Owner 요청: 기존 #4194의 “건강한 모델 추론을 20/30/45/60초에 자르지 않는다”를 전 제품 모델 호출 경로에서 다시 확인한다. **무제한 네트워크 대기**나 모든 도구에 `timeout=None` 적용을 의미하지 않는다.

## 1. 장애 경계

관측: Gemma 4 31B가 B14에서 30.5초 `upstream_timeout` 후 실패한 반면, 별도 정상 호출은 31.8초에 완료됨. B14의 기존 `connect=30` / 해당 모델만 `connect=55`라는 모델별 임시 완화는 **원인 검증 없이 전체 아키텍처를 좁게 해결한 조치**였다. Cloudflare Python Workers에서 HTTPX는 Fetch 구현을 사용하므로 ConnectTimeout 표시는 실제 TCP 연결과 응답 헤더 대기를 확실히 분리하지 못한다. **실제 Worker의 개별 phase safe log 검증 전에는 이 가설을 원인 확정으로 주장하지 않는다.**

본 변경은 첫 응답 헤더 도착을 **동일한 모델 유휴 예산 600초**로 설정해 30/55초의 인위적 조기 중단을 제거한다. 건강한 SSE 스트리밍이 진행되는 동안 누적 600초를 기계적으로 적용하지 않으며, 청크마다 별도 600초 유휴 감시를 재시작한다. completed 응답은 호출자별 설정 예산 안에서 끝나야 한다.

## 2. 실제 모델 경로별 Source readback

| 위치 | 모델 추론/첫 응답 이전 | 이 변경 후 | 변경 여부 |
|---|---|---|---|
| B14 `platform.py` completed + SSE Provider | HTTPX connect=30s, Gemma31 55s; read=600s | connect=600s/read=600s (동일 모든 모델) | 변경 |
| B14 `provider.py` legacy/BYOK | connect=min(model budget,30s), read=budget | connect=budget, read=budget | 변경 |
| AI Core `b14_execution.py` B14 completed | connect=min(budget,30s), read=budget | connect=budget, read=budget | 변경 |
| AI Core `b14_streaming.py` B14 SSE | connect=min(budget,30s), per-event idle=budget | connect=budget, per-event idle=budget | 변경 |
| PADIEM Chat B62 `app/config.py` & `worker_config.py` | completed + streaming default=600s | 600s | 소스 감사, 기존 유지 |
| Engine `worker.py` B14 client | default=600s | 600s | 소스 감사, 기존 유지 |
| Engine Worker JS Fetch transport | `read` timeout 우선 사용(모델 기본 600s) | 600s | 소스 감사, 기존 유지 |
| P01/Hark/Claw Agent/Task | 고정 총 경과시간이 아닌 진행 기반 유휴 감시(#4323) | 기존 정책 유지 | 소스 감사, 운영 E2E 별개 |
| Living Fiction/Learning/Travel & Personal Edition | 직접 모델 공급자 기본600s (source settings) | 600s | 소스 감사, 기존 유지 |

중요: **B14의 `GATEWAY_WALL_SECONDS=45`는 첫 물리 모델 호출의 하드컷이 아니라 후속 재시도/대체 호출의 예산이다.** Owner의 수동 exact route에서는 자동 대체와 자동 재시도를 켜지 않는다. 단계별 `write=20`, `pool=10`은 요청 전송/연결풀 자원 보호용이고, 추론의 생성 시간이 아니다.

모델 실행과 무관한 **웹검색 15초, OAuth/인증 8–15초, 로컬 페어링 10초, 일정/외부 도구 30–60초, PDF 처리, 승인 lease/fencing** 제한을 변경하면 자원 고갈 및 승인/중복 실행 사고가 가능하므로 그대로 둔다.

## 3. Acceptance / 검증 진실성

1. 오프라인 B14 completed/SSE `httpx.MockTransport`에 model별 동일 connect/read600 확인. Legacy/BYOK, Core/Engine 실제 `httpx.Request.extensions.timeout` 회귀 및 #4194 전 제품 소스 기본값 검사.
2. PR exact-head CI GREEN, 합법적 main squash merge.
3. B14 Production canonical exact-main deploy + 운영 `/health`·`/models` 일치 및 단발 모델 smoke. Core 코드 변경은 **Engine/B62 소스가 동일한 main을 배포할 때 반영**되므로 B14 배포만으로 전체 운영 검증 완료 아님.
4. B62·Engine의 운영 **실효 binding/override 값** 및 브라우저/Worker→Engine→B14 SSE 완료를 직접 확인해야 제품 E2E PASS. 600s default는 Worker 환경변수에 단축 override가 없는 경우에만 해당함.
5. Gemma31 실제 30~600초 구간 성공 및 Agnes429 해소는 **이번 오프라인 Source 정합화만으로 증명 불가**. HTTP429는 별도 #4441 공급사 정책·할당량/Worker-origin 검증이 필요하다.

## 4. 이슈/변경 추적

- 신규 #4442 전 제품 모델 first-response 중단 정책
- 이전 #4194 공통 600초 정책 및 #4200 원 소스 변경
- Gemma 전용 임시 #4437/#4440 (이번 일관된 정책으로 후속 대체)
- Agnes 429 운영·공급사 진단 #4441
- 보안 원칙: API 키/세션/고객 입력 노출, 자동 대체/재시도 증설, 모델 계정/공급사 라우팅 변경 금지
