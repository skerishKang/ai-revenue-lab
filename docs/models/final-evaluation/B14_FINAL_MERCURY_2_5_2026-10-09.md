# B14 신규 독립 최종 평가 — Inception Mercury 2.5

**평가 라운드:** `B14_FINAL_MODEL_EVALUATION_2026-10-09`
**평가일:** 2026-10-09 (KST)
**B14 사용자 명시 선택 모델:** `inception/mercury-2.5`
**공식 제공자 upstream:** `mercury-2.5`
**상태:** **IN_PROGRESS / B14_PREFLIGHT_HTTP403 / DIRECT_TIMEOUT_PARTIAL** — 최종 승인 및 고객 Production 동작 검증 아님.

## F1 — 제공자 공식 문서

- 공식 제공자: [Inception Models](https://www.inceptionlabs.ai/models), [Mercury 2.5 발표](https://www.inceptionlabs.ai/blog/introducing-mercury-2-5) (2026-09-08).
- OpenAI 호환 `POST https://api.inceptionlabs.ai/v1/chat/completions`, upstream `mercury-2.5` 공식 예시 확인.
- 공식 컨텍스트 **260K tokens**; reasoning, tool use, structured output 명시.
- 최대 출력 토큰: 공식 확인 자료에서 **UNKNOWN** (타사 모델 표의 66K를 공식 한도로 이월하지 않음).
- Tunable reasoning 제공자 발표로 확인; **Mercury 2.5 고유 모드·기본값의 공식 근거 불충분 → UNKNOWN**. Mercury 2 과거 모드 설명을 2.5에 자동 적용 금지.
- 공개 가격은 수시 할인·플랜 변경 가능. 현재 API 프로젝트 실제 과금이나 무료 잔여량은 별도.

## F2 — B14 등록 및 계정 실제 한도

- B14 단일 registry JSON: `inception/mercury-2.5` enabled, 제공자 `inception` enabled, upstream `mercury-2.5`, fixed HTTPS origin `https://api.inceptionlabs.ai/v1`, 고정 Secret 바인딩 `PADIEM_INCEPTION_MERCURY_API_KEY` 확인.
- 해당 로컬 OpenCode 제공자 설정에 API 키·공식 baseURL이 존재한다는 **존재성만** 확인. 비밀값 노출·커밋 없음.
- **현재 실서비스 B14 GET `/api/pilot/health`와 `/api/pilot/models` 모두 HTTP403** (2026-10-09 재조회). 모델별 `registered`·`has_key`를 이 시점의 served Worker에서 확인할 수 없었다. 소스 등록과 Production readiness 구분.
- **B14 POST 0회**. GET preflight 단계가 실패했으므로 Mercury B14 경유 429/504/정확도를 측정한 것으로 주장하지 않는다.
- 연결된 Inception 계정의 실제 Free/Paid, RPM, TPM, RPD, 잔여 크레딧 **UNKNOWN**. 공개 일반 플랜과 계정별 적용 한도 혼동 금지.

## F3 — 파라미터와 출력 예산

- B14 `gateway.py` request schema는 `model`, `messages`, `temperature`, `max_tokens`를 허용하고 현재 **명시적 `max_tokens`는 4,096 상한**. 실측 direct 1,800은 허용 예산 내.
- 공통 `platform.py` 완료형 POST는 fixed upstream model/messages, 선택적 temperature/max_tokens만 전달. `reasoning_effort`를 공식적으로 Mercury 2.5에 전달했다고 주장할 수 없다.
- 본 신규 독립 평가는 `reasoning_effort` 미지정·`temperature=0`·`max_tokens=1,800`; 모델 기본값을 강제로 추정하지 않음.
- Reasoning 내부 사용량은 응답의 usage `completion_tokens_details.reasoning_tokens`로 실제 관측. 모드 설정 유효성은 **NOT_TESTED**.
- 다른 모델/사용자 기본 모델의 변경은 없음.

## F4–F5 — 합성 QKR 직접 API 실측

동일한 합성 한국어 견적 corpus `QKR-001..010` 및 공통 `PROMPT_HEADER`를 사용. 각 문항 1회, `mercury-2.5` exact ID, temperature 0, max_tokens 1,800, no retry, no fallback. B66 `quote-extraction.js` 정규화 후 필드·품목 정확도 채점. 요청·응답 원문과 비밀값을 GitHub에 저장하지 않음.

| 문항 | 직접 upstream 상태 | 엄격 견적 내용 | 지연 | 총 토큰 | reasoning 토큰 | 완료 사유 |
|---|---|---|---:|---:|---:|---|
| QKR-001 | HTTP 200 | **FAIL**: `project_name` 불일치, 품목 전부 정확 | **5,907ms** | **1,184** | **871** | stop |
| QKR-002 | HTTP 200 | **PASS**: 모든 필드·품목 정확 | **3,656ms** | **1,465** | **1,064** | stop |
| QKR-003 | **응답 미수신 / 65초 클라이언트 제한** | **UNAVAILABLE**, 정확도 채점 금지 | **65,078ms** | — | — | — |
| QKR-004~010 | **NOT_ATTEMPTED** | NOT_TESTED | — | — | — | — |

- 실행 전체: **3/10 attempted**, **2/3 HTTP200**, **1/2 정상 응답 중 strict PASS**, 1개 클라이언트 타임아웃(HTTP status 없음), 7개 미시도.
- 위의 2개 정상 응답 평균 지연 **4,782ms**, 평균 총 토큰 **1,324.5**. 대표 성능 추정치가 아닌 일부 관측값.
- 429/504는 이 3건에서 **관측되지 않음**. 타임아웃을 504로 잘못 변환하거나 모델 품질 실패로 채점하지 않는다.
- timeout 1건 발생 직후 **추가 호출 중단**, 재시도·모델 교체 없음.
- 신규 local evidence: `E:\\b14-mercury25-DIRECT-10QKR-20261009.json`. 로그는 metadata/비밀값 제거 결과만, 고객 자료 없음.

## F6 — B66 QuoteCore → 실제 PDF

**NOT_TESTED.** QKR-008은 직접 평가에서 요청하지 않았기 때문에 Mercury 2.5의 실제 12품목 추출 응답→QuoteCore→PDF E2E 성공을 주장하지 않는다. 이전 모델의 PDF 증거를 재사용하지 않는다.

## 현재 독립 평가 판정

| 게이트 | 결과 |
|---|---|
| F1 공식 모델/사양 | PARTIAL (최대 출력·리즈닝 기본값 UNKNOWN) |
| F2 등록·실제 계정 한도 | SOURCE_REGISTERED / ACTUAL_QUOTA_UNKNOWN |
| F3 B14 파라미터 | SOURCE_REVIEWED / REASONING_PASS_THROUGH_NOT_PROVEN |
| F4 B14 Production | **BLOCKED_PREFLIGHT_HTTP403**, 0 POST |
| F4 direct | **2/3 HTTP200, 1 timeout**, 즉시 중단 |
| F5 견적 품질 | 정상 응답 2개 중 1개 PASS, 8개 미완료 |
| F6 고객 PDF | NOT_TESTED |
| **최종 모델 승인** | **IN_PROGRESS — 승인 불가**, 다음 검증 필요 |

**다음 단계:** B14 GET 403 접근 조건 별도 해소 → exact-model direct/B14 재개 가능 여부 검증 → 계정 실제 RPM/TPM/RPD와 2.5 reasoning 값 권위 자료 확보 → 제한된 추가 QKR 및 PDF. 무단 반복 호출이나 자동 모델 대체는 하지 않는다.

**Owner 우선순위:** Mercury 2.5(7번) → Atria Dawn Preview(8번) → `ERROR_B14_HTTP429 / DEFERRED` Agnes 3.0 Flash(9번). 이 순서 변경은 오직 평가 문서이며 B14 제품의 노출·등록 순서를 강제로 바꾸지 않는다.
