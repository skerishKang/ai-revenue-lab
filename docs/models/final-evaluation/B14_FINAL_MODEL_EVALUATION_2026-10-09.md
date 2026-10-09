# B14 최종 모델 평가 — 신규 독립 평가 원본

| 항목 | 값 |
|---|---|
| 라운드 ID | `B14_FINAL_MODEL_EVALUATION_2026-10-09` |
| 최초 작성 | 2026-10-09 (KST) |
| 현재 상태 | **IN_PROGRESS — 최종 결과 미확정** |
| 최종 선정권 | Product Owner |
| 평가 기준 | 동일 절차, 모델별 실제 증거, 사용자 명시 선택 |

## 1. 이전 평가와 명확히 분리

**이 문서는 지금 새로 시작한 B14 최종 모델 평가의 독립 원본이다.** 과거 견적 추출 비교·초기 스모크·모델 선정 메모를 이 문서의 점수와 섞지 않는다.

- 기존 `docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md`, 이슈 #2676과 예전 평가 기록은 **이전 라운드**로 보존한다.
- 기존 평가에서 어떤 모델이 몇 점을 받았더라도 **이번 최종 평가의 점수로 이월하지 않는다.**
- 이번 라운드에서는 모델별로 사양, 실제 프로젝트 할당량, 리즈닝과 토큰 파라미터, 직접 호출 품질, 견적서 추출, 최종 PDF까지 **신규 검증**한다.
- 한 모델을 끝낸 뒤 동일한 절차로 다음 모델을 진행한다. 모델을 자동 선정하거나 실패한 모델을 다른 모델로 자동 대체하지 않는다.
- 모델 ID와 현재 등록 상태는 `apps/korean-ai-platform/app/pilot/b14_models.json`, Owner 승인 규칙은 `docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`에서 확인한다.

## 2. 최종 평가의 6가지 관문

| 관문 | 평가 내용 | 증거 |
|---|---|---|
| F1 공식 모델 능력 | exact ID, 입력 컨텍스트, 최대 출력, 입력 유형, 리즈닝 값·기본값 | 제공자 최신 공식 사양 |
| F2 실제 프로젝트 제한 | Free/Paid, 실제 RPM, 입력 TPM, RPD 및 그 밖의 모델별 사용 한도 | 해당 프로젝트 대시보드 |
| F3 B14 모델 설정 | 토큰 명시·생략, 리즈닝 전달, 기본값, 예외, 다른 모델 영향 | 소스 테스트와 모의 제공자 요청 |
| F4 실제 제공자 호출 | 정확한 모델·업스트림, 응답·완료 사유, 토큰 사용, 429/504, 지연 | 새로운 제한된 실제 호출 |
| F5 견적서 내용 추출 | 이번 라운드 QKR-001~010, 복수 품목·수량·단가·정정·결측 | 실제 모델 응답의 QuoteDraft 검증 |
| F6 최종 견적 PDF | 추출→QuoteCore 계산→저장 양식→실제 PDF 다운로드 | 금액·필드·12개 품목·페이지 흐름 E2E |

최종 모델은 **F1–F6가 이번 라운드에서 검증된 뒤에만** `FINAL_PASS` 여부를 판단한다. `UNKNOWN`, `NOT_TESTED`는 품질 불합격과 다르며, 승인·등록·운영 배포와도 별도이다.

**서로 다르게 관리할 제한:** 모델 최대 출력 ≠ B14 명시적 요청 제한 ≠ 해당 프로젝트의 실제 무료 RPM/TPM/RPD ≠ 제품별 적정 출력 예산. 모델의 이론적 최대 출력을 모든 요청에 강제로 적용하지 않는다.

## 3. 이번 라운드 대상 및 진행 상태

| 평가 순서 | exact 모델 ID | 신규 최종 평가 진행 상태 |
|---:|---|---|
| 1 | `google/gemini-3.1-flash-lite` | **F1 확인·F3 소스 파일럿 테스트 PASS, 실제 호출·최종 견적/PDF 미검증** |
| 2 | `google/gemini-3.5-flash-lite` | `NOT_STARTED` |
| 3 | `google/gemma-4-26b-a4b-it` | `NOT_STARTED` |
| 4 | `google/gemma-4-31b-it` | `NOT_STARTED` |
| 5 | `poolside/laguna-s-2.1` (**직접 API**) | `NOT_STARTED` |
| 6 | `sensenova/sensenova-6.8-flash-lite` | `NOT_STARTED` |
| 7 | `agnes-ai/agnes-3.0-flash` | `NOT_STARTED` |
| 8 | `inception/mercury-2.5` | `NOT_STARTED` |
| 9 | `atria/Atria-Dawn-Preview` | `NOT_STARTED` |

**추가 평가 후보:** ZCode에 별도로 등록된 `stepfun/step-5-preview-free`는 현재 B14 9개에는 속하지 않는다. B14 경유 없이 로컬 단일 모델 호출을 검증하고 필요하면 별도 후보로 평가한다. 기존 9개 운영 모델 목록과 혼합·자동 대체하지 않는다.

표의 순서는 작업 순서이지 성능 순위나 기본 모델 우선순위가 아니다.

## 4. 첫 번째 모델: Gemini 3.1 Flash-Lite

### F1 — 공식 사양: 확인됨

| 항목 | 확인값 |
|---|---|
| B14 exact ID | `google/gemini-3.1-flash-lite` |
| Google upstream | `gemini-3.1-flash-lite` |
| 입력 컨텍스트 | **1,048,576 tokens** |
| 이론적 최대 출력 | **65,536 tokens** |
| 리즈닝 값 | **minimal / low / medium / high** |
| 리즈닝 기본값 | **minimal** |
| Google OpenAI 호환 리즈닝 필드 | `reasoning_effort` → Gemini thinking level |
| 공식 지원 입력 | 텍스트·이미지·동영상·오디오·PDF |

공식 문서: [Gemini 3.1 모델 카드](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [OpenAI 호환](https://ai.google.dev/gemini-api/docs/openai), [Gemini 3 리즈닝](https://ai.google.dev/gemini-api/docs/gemini-3).

### F2 — Google 프로젝트 실제 한도: 미확인

| 값 | 이번 평가 상태 |
|---|---|
| 실제 프로젝트 Free / Paid 티어 | **UNKNOWN** |
| Gemini 3.1 활성 RPM | **UNKNOWN** |
| Gemini 3.1 활성 입력 TPM | **UNKNOWN** |
| Gemini 3.1 활성 RPD | **UNKNOWN** |
| 실제 현재 사용량과 추가 제한 | **UNKNOWN** |

Google의 한도는 **API 키 개수가 아니라 프로젝트 단위**이며, RPM·입력 TPM·RPD 중 한도 하나를 넘어도 제한이 발생할 수 있다. 실제 수치는 [Google AI Studio Rate Limits](https://aistudio.google.com/rate-limit)에서 그 키가 연결된 프로젝트 기준으로 확인한다. 공식 규칙: [Gemini API Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

**주의할 기술적 구분:** `65,536`은 모델의 최대 출력 능력이다. 무료 프로젝트가 매 호출마다 그만큼 허용한다는 뜻이 아니다.

### F3 — B14 토큰·리즈닝 소스 파일럿: 모의 테스트만 완료

로컬 브랜치 `feat/b14-gemini31-parameter-profile-261009`에서 **이 모델 하나에만** 공식 최대 출력 메타데이터와 `reasoning_effort` 전달 규칙을 적용하는 파일럿을 만들었다.

| 검증 | 결과 |
|---|---|
| `max_tokens` 생략 → 제공자 기본값 | **LOCAL_PASS** |
| `max_tokens=4096` 허용 | **LOCAL_PASS** |
| `max_tokens=4097` 거부 (기존 B14 명시적 상한 유지) | **LOCAL_PASS** |
| 네 가지 명시적 리즈닝 수준만 허용 | **LOCAL_PASS** |
| 생략 시 임의로 리즈닝 수준 주입하지 않음 | **LOCAL_PASS** |
| 다른 8개 모델은 기존 파라미터 계약 유지 | **LOCAL_PASS** |
| 소스 전체 B14 회귀 | **1,013 tests PASS** |

위 결과는 **로컬 소스와 모의 HTTP 요청 테스트 결과**다. `main` 병합, Production 배포, 실제 Google 리즈닝 4단계 수락, 계정 한도 검증은 이 결과로 입증되지 않는다. 모든 모델의 요청 최대값을 일괄 확대하지 않았다.

### F4–F6 — 이번 신규 최종 평가에서 아직 실행하지 않은 시험

| 관문 | 상태 | 다음 측정 |
|---|---|---|
| F2 | `UNKNOWN` | 실제 프로젝트의 티어·RPM·TPM·RPD |
| F3 실제 업스트림 적합성 | `NOT_TESTED` | 선택 리즈닝 4단계 제한 호출·응답·usage·finish_reason |
| F4 모델 호출 안정성 | `NOT_TESTED` | 표본 수·429/504 분리·지연 |
| F5 10개 견적 추출 | `NOT_TESTED` | 동일 QKR 시험 **이번 평가에서 새로** 시행 |
| F6 고객용 PDF E2E | `NOT_TESTED` | 저장된 견적 양식으로 PDF까지 연결 |
| **최종 모델 판정** | **IN_PROGRESS** | F1–F6 종합 후 Owner가 채택 판단 |

## 5. 이후 모델에도 동일하게 기록하는 형식

```text
EVALUATION_ROUND = B14_FINAL_MODEL_EVALUATION_2026-10-09
MODEL_ID = <exact provider/model ID>
UPSTREAM = <actual exact upstream>
OFFICIAL_INPUT_MAX = <value or UNKNOWN>
OFFICIAL_OUTPUT_MAX = <value or UNKNOWN>
REASONING_LEVELS_AND_DEFAULT = <official or UNKNOWN>
PROJECT_TIER_RPM_TPM_RPD = <observed values or UNKNOWN>
B14_PARAMETER_TEST = PASS | FAIL | NOT_TESTED
ACTUAL_REASONING_PROBE = PASS | FAIL | NOT_TESTED
REAL_PROVIDER_AVAILABILITY = <n successes / n attempts; 429/504 separate>
NEW_QUOTE_EXTRACTION = <n/10 and per-case errors>
FINAL_QUOTE_PDF_E2E = PASS | FAIL | NOT_TESTED
FINAL_VERDICT = FINAL_PASS | FAIL | IN_PROGRESS
EVIDENCE = <source SHA, dated real-call markers, tested PDF evidence>
```

**갱신 원칙:** 모델 하나가 검증될 때 이 문서의 해당 결과만 갱신한다. 이전 라운드 성능 점수, 다른 경로의 추정값, 나머지 모델의 미검증 항목을 자동으로 채우지 않는다.
