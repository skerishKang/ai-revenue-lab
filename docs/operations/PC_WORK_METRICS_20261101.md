# 원격 PC 작업 측정 1단계 (#6460 §5-1)

코드·모의 시험·push 범위다. 배포, 운영 DB 변경, 실제 PC·모델 호출은 하지 않았다.
브랜치는 `feat/pc-work-metrics-261101`이며, 아직 main에 없는 하네스 1~3단계를 포함한
`feat/pc-delegation-261101`의 `8850e32bf151d89ff1a66000b5f970b2f8cc29e6`에서 시작했다.

## 수집 위치와 단위

Engine의 공통 PC 실행 단계에서 수집한다. 도구별 구현에는 계측 코드를 넣지 않는다.

- `pc_work_metrics.py`: 턴별 ContextVar 수집기와 공통 handler/서명 전송 관찰.
- `claw_pc_query_step_driver.py`: 기존 공통 handler 등록, 확인 질문, 모델 단계 입력·usage 연결.
- `orchestration_service.py`와 운영 `orchestration_identity_service.py`: JSON·스트림 턴 시작과 종료.
- `pc_tools_turn.py`: native 최초 모델 호출과 기존 fallback도 같은 수집기에 포함.

턴 참조는 서버가 `(app_id, canonical subject, session_id/pc_run_id)`를 해시한
`pcturn_…`이다. Core 내부 child run이나 모델 호출마다 새 턴을 만들지 않는다.
동시 요청은 분리하고 idempotency replay는 도구 실행·최종 보고를 다시 세지 않는다.

PC 왕복은 **서버가 접수한 고유 dispatch ID 수**다. context/status/result HTTP 폴링,
같은 명령 내부의 결과 확인, 같은 dispatch 재조회는 새 왕복으로 세지 않는다.
Mesh 내부 패킷 수나 네트워크 재전송 횟수는 이 값의 의미가 아니다.
하네스가 질문으로 끝내면 실행된 도구 수와 PC 왕복 수는 0이다.

## 기록 필드

| 필드 | 의미 |
|---|---|
| `calls`, `tool_calls` | 실제 공통 handler 진입 수와 도구별 집계 |
| `pc_round_trips` | 접수된 고유 PC 명령 수 |
| `truncation_count` | 명시적으로 잘렸다고 보고된 결과 수 |
| `truncated_bytes_known` | 원본·전달 바이트 증거가 있는 잘림의 차이 합계 |
| `truncated_bytes_unknown_count`, `truncated_bytes` | 원본 길이를 모르는 잘림 수. 하나라도 있으면 전체 잘린 바이트는 `null` |
| `timeout_count` | 공통 PC 전송·본문 읽기·handler TimeoutError, HTTP 504, `timed_out` 결과. 같은 호출 안에서 중복 집계하지 않음 |
| `model_calls` | native 최초 호출과 후속 단계·기존 fallback 호출 수 |
| `model_input_tokens` | 모든 호출에서 공급자 입력 토큰이 관측됐을 때의 합계. 누락이 있으면 `null` |
| `model_input_tokens_observed`, `model_input_tokens_missing_calls` | 관측된 입력 토큰 합계와 usage 없는 호출 수 |
| `model_input_tokens_estimated`, `tool_result_tokens_estimated` | 각 모델 호출의 직렬화된 입력·도구 결과 UTF-8 바이트 / 4 추정치. 재전송한 결과는 다시 합산 |
| `tool_result_input_ratio`, `token_ratio_basis` | 위 추정치끼리의 비율. `utf8_bytes_div4_estimate`로 표시하며 실제 tokenizer 측정값으로 주장하지 않음 |
| `outcome`, `outcome_reason` | 실행기 종료 상태와 구조적으로 관측한 사유 |

`completed`는 실행기가 정상 terminal까지 간 상태다. 모델의 “완료했습니다” 문장을 판독해서
성공으로 올리지 않는다. 도중 tool/model 실패가 있었으면 정상 종료 뒤에도 `tool_failed`,
`tool_timeout`, `model_failed`, `model_timeout` 사유를 남긴다. 실제 사용자 목표 달성 여부를 추정하지 않는다.
확인 질문은 `confirmation_required`, 실행 오류는 `failed`, 취소는 `cancelled`,
생산자까지 취소되는 소비자 이탈은 `abandoned/client_disconnected`로 구분한다.
Chat의 연결 종료만으로 백그라운드 실행을 실패라고 판정하지 않는다.

현재 PC 읽기 경로는 큰 결과를 잘라 성공시키지 않고 전체 전달하거나 거부한다.
`output_too_large`만으로 잘림을 추정하지 않는다. 구형 목록의 `truncated=true`에 원본 길이가
없으면 횟수만 기록하고 바이트는 미상으로 둔다.

## 기존 B14 장부에 저장

새 저장소·표를 만들지 않는다. 기존 `b14_model_call`에 다음 두 nullable 열을 추가한다.

- `pc_work_metrics_json`: 숫자·고정 도구 ID·고정 종료 사유만 가진 최종 요약.
- `pc_work_metrics_recorded_at`: B14가 기록한 시각.

기존 `product`, `subject_ref`, `session_ref`로 실제 모델 호출 행을 찾아 **한 행에만** 붙인다.
`X-Request-Id` 추적은 유지하고 기존 product/subject/session 헤더를 함께 보낸다.
재전송은 멱등이고 다른 요약으로 덮어쓰지 않는다. 여러 모델 호출 행을 턴 여러 개로 합산하지 않는다.
공급자가 기록한 토큰·비용·시도 내역은 변경하지 않는다.

B14 자체 migration 순서인 `apps/korean-ai-platform/migrations/0003_pc_work_metrics.sql`을 쓴다.
Chat DB migration 087은 필요하지 않아 사용하지 않는다. COM2의 기존 B14 migration loader가 적용하며,
같은 revision의 공통 계약 모듈을 포함하도록 기존 staging 목록과 COM2 설치 스크립트도 준비했다.

## 조회와 전달

- 최종 보고: `POST /api/pilot/v1/internal/pc-turn-metrics`
- 최근 작업: `GET /api/pilot/v1/admin/model-calls/pc-turns?limit=N`

둘 다 기존 B14 서버 간 HMAC 인증을 사용한다. 새 토큰·비밀·환경 변수는 없다.
조회는 기존 관리자 필터와 limit 계약을 재사용하며, 최근 N개 고유 턴의 평균·최대,
종료 상태·사유, 잘림/시간 초과가 많은 도구 순위를 반환한다.
평균·최대에는 미상 값을 0으로 넣지 않고 관측/누락 턴 수를 함께 반환한다.
모델 기록은 있지만 최종 보고가 없는 턴도 `not_finalized`로 표시한다.
진행 중인지 프로세스 중단으로 보고를 못했는지 증거가 없으면 둘 중 하나로 단정하지 않는다.

B14의 기존 지연 저장과 경합하면 `ledger_pending`을 반환한다. 보고기는 기존 저장 대기 범위인
5초 안에서 동일한 요약을 다시 보낸다. 저장소 장애로 측정을 기록하지 못해도 PC 작업 답변은
실패로 바꾸지 않고 값 없는 전달 상태 로그만 남긴다. 본문·경로·명령·인자·비밀 값은 지표에 저장하지 않는다.

## 검증

모의 PC·모델로 일반 JSON, 스트림, native JSON, native 스트림을 실제 실행기에 통과시켰다.
실제 공통 수집기 → 기존 서명 transport → B14 인증 route → migration 적용 SQLite → 최근 N개 요약을 확인한다.
왕복 중복 제거, 알려진/미상 잘림 바이트, fetch/본문 읽기 시간 초과, 토큰 누락,
동시 턴 격리, replay, 확인 질문·취소·이탈, 보고 재시도·충돌, 미완료 보고도 검사한다.
기존 하네스·사후 검증·위임·모델 transport·B14 장부 회귀시험을 함께 실행한다.

결과: Engine 관련 489개, B14 장부·마이그레이션·설치 준비·게이트 정적 시험 128개 통과.
조회 보강 후 실제 Engine→B14 통합과 lifecycle 22개도 통과했다.
`bash -n`, `git diff --check` 통과. 설치 시험은 임시 경로와 무동작 systemctl 대역만 사용했다.
