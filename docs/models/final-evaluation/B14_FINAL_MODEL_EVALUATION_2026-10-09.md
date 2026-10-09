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
| 1 | `google/gemini-3.1-flash-lite` | **F1 확인 / F2 무료 한도 확인 / F3 LOCAL_PASS / F4 HTTP200 10/10 / F5 엄격 7/10 / F6 NOT_TESTED** |
| 2 | google/gemini-3.5-flash-lite | **F1/F2 확인·Google 직접 40회: Minimal 10/10(1.09s), Medium 10/10(2.36s)·기본 Minimal 추천·로컬 PDF PASS(12품목 2페이지)·고객 F6 미완료** |
| 3 | `google/gemma-4-26b-a4b-it` | **공식 사양·Free 30RPM/16K TPM/14.4K RPD, 직접 Minimal 8/10(3.26s)·High 엄격 JSON 0/10(20.62s), B14 504, 로컬 PDF 12품목 2페이지** |
| 4 | `google/gemma-4-31b-it` | **F1 Dense 30.7B·출력 32,768 / F2 30RPM·16K TPM·14.4K RPD / Minimal 원본 1/10·내용 5/10 / High 원본 0/10·내용 0/10 / B14 504** |
| 5 | `poolside/laguna-s-2.1` (Poolside 직접 API, Kilo 제외) | **F1 공식 118B/활성8B·1M / F2 계정한도 UNKNOWN / 직접 기본 9/10(10.89s), 추론 끔 8/10(4.63s), 켬 8/10(9.56s) / B14 9/10 HTTP200 / 실제 AI→PDF PASS** |
| 6 | `sensenova/sensenova-6.8-flash-lite` | **F1 제공자 262,144/65,536 · F2 계정 한도 UNKNOWN · B14 10/10 · 직접 기본 10/10 · 리즈닝 none 10/10 2633ms; low 10/10 6528ms; medium 10/10 6278ms; high 10/10 6503ms · 12품목 로컬 PDF PASS** |
| 7 | `agnes-ai/agnes-3.0-flash` | **IN_PROGRESS / RATE_LIMIT_BLOCKED** — B14 첫 요청 429(0/1 HTTP200), Agnes 직접 10/10 HTTP200·견적 정확도 8/10(3,569ms/477토큰), Thinking Off 5/5(2,563ms/399토큰)·On 5/5(7,053ms/717토큰), 11번째 비교 호출 429 중단, 12품목 QuoteCore PDF PASS(2페이지), F2 계정 한도 및 고객 저장 PDF E2E UNKNOWN/NOT_TESTED. [상세](B14_FINAL_AGNES_3_0_FLASH_2026-10-09.md) |
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

### F2 — Google AI Studio 무료 티어 할당량: 사용자 제공 화면에서 확인 (2026-10-09)

사용자가 Google AI Studio의 **무료 티어 Rate limits 실제 표**를 제공했다. 이 라운드에 기록할 수 있는 계정 화면 기준 수치가 확보됐다. 이전의 전체 'UNKNOWN' 표시는 더 이상 현재 자료에 맞지 않는다.

| B14 exact Google 모델 | 화면 표시명 | RPM | 분당 입력 TPM | RPD |
|---|---|---:|---:|---:|
| google/gemini-3.1-flash-lite | Gemini 3.1 Flash Lite | **15** | **250,000** | **500** |
| google/gemini-3.5-flash-lite | Gemini 3.5 Flash Lite | **15** | **250,000** | **500** |
| google/gemma-4-26b-a4b-it | Gemma 4 26B | **30** | **16,000** | **14,400** |
| google/gemma-4-31b-it | Gemma 4 31B | **30** | **16,000** | **14,400** |

- **이용 등급: 무료(Free)** — 사용자가 무료 티어 화면이라고 확인했다.
- 화면의 '0 / 15'는 **사용 0 / 허용 15**이다. 캡처 시점 네 모델 모두 요청량·입력 토큰·일일 요청의 사용량은 0으로 표시돼 있다.
- **RPM, 입력 TPM, RPD는 실제 무료 티어의 이용 한도**이지, 모델의 최대 출력 토큰이나 컨텍스트 한도가 아니다. 출력 최대치 65,536토큰 및 B14 명시적 출력 예산 4,096과 혼동하지 않는다.
- 같은 화면의 Gemma 4는 26B/31B로 표기된다. B14의 exact upstream ID와 무료 티어 화면 표시명이 동일 모델을 가리키는지는 별도 API 매핑으로 확인한다.
- 프로젝트 ID가 제공되지 않았으므로 **B14 Worker의 현재 API 키와 동일 프로젝트인지 여부는 미확인**이다. 수치 자체는 사용자가 제시한 AI Studio 무료 티어 표에 근거한 이번 프로젝트 평가 자료로 기록한다.
- 전체 **45개 모델, 21개 도구**의 모든 행은 [AI Studio 무료 티어 한도 전체 표](GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.md)와 [구조화 JSON](GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.json)에 분리 저장했다. 검색/지도 그라운딩은 추론 RPM·TPM·RPD와 별도다.
- 한도는 **2026-10-09 캡처 기준**이다. 향후 계정 변경 및 한도 조정 시 날짜와 출처를 새로 기재한다.

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

### F4–F5 — 이번 신규 최종 라운드 실제 Gemini 3.1 견적 10건 (2026-10-09)

**이번 평가에서 새로 10회 요청을 실행했다.** 과거의 41회 비교 점수를 가져온 것이 아니다. exact route google/gemini-3.1-flash-lite, upstream gemini-3.1-flash-lite에 합성 QKR-001~010 각각 단 1회; max_tokens=1,800, temperature=0, 호출 시작 간 최소 8초 간격; 자동 재시도·다른 모델 대체 없음.

| 항목 | 이번 라운드 결과 |
|---|---|
| 실제 Google 제공자 요청 | **10건** |
| HTTP 200 / 429 / 504 | **10 / 0 / 0** |
| 필드·품목 내용 일치 | **8/10** |
| 경로 메타데이터 검증까지 포함한 엄격 통과 | **7/10** |
| QKR-002 | 내용은 정확. 경로 메타데이터 일치 검증 **실패**, HTTP 200, 24,764ms |
| QKR-004 | project_name 필드 오류, HTTP 200, 1,483ms |
| QKR-007 | project_name 및 일부 품목 필드 오류, HTTP 200, 2,093ms |
| 최소·평균·최대 응답시간 | **1,359 / 5,968 / 24,764ms** |
| 실제 리즈닝 4단계 호출 검증 | **NOT_TESTED** (시범 변경 브랜치의 모의 HTTP 검증만 통과) |
| 최종 PDF 생성 연결 | **NOT_TESTED** (별도 B66 레이아웃 보정 중) |

QKR-002의 메타데이터 검증 실패는 다른 모델로 대체됐다는 확증이 아니다. 정확한 실패 필드를 확인해야 한다. **모델의 추출 정확성 8/10과 시스템의 엄격 검증 7/10을 혼동하지 않는다.**

로컬 검증 기록: Padiem-Command-Center의 E:\b14-gemini31-FINAL-20261009-safe-results.json (합성 시험, 메타데이터만 기록).

### Gemini 3.1 최종 검증 잔여 작업

| 관문 | 현재 상태 | 다음 검증 |
|---|---|---|
| F1 공식 모델 사양 | CONFIRMED | 신규 모델 사양 변경 시 재확인 |
| F2 무료 티어 RPM·입력 TPM·RPD | **CONFIRMED_FROM_OWNER_AI_STUDIO_SNAPSHOT** | 실제 Worker 키가 같은 프로젝트 소속인지 확인 |
| F3 소스 파라미터 검증 | LOCAL_PASS | 실제 Gemini 요청에서 리즈닝 4단계 수락 여부 확인 |
| F4 신규 호출 | HTTP200 10/10 | QKR-002 경로 메타데이터 불일치 원인 조사 |
| F5 견적 추출 | CONTENT_MATCH 8/10 / STRICT_PASS 7/10 | QKR-004/007 오류 수정 및 재평가 |
| F6 고객용 견적 PDF | NOT_TESTED | B66 레이아웃 수정 후 저장 양식으로 최종 PDF E2E |
| **최종 모델 판정** | **IN_PROGRESS** | 모든 관문 충족 시 Owner 최종 평가 |


## 5. Gemini 3.5 Flash Lite — 신규 최종 평가

- 공식 모델 능력: 입력 1,048,576토큰, 최대 출력 65,536토큰, 리즈닝 minimal/low/medium/high, 기본 minimal.
- AI Studio 무료 티어: RPM 15, 입력 TPM 250,000, RPD 500.
- 이번 신규 API 10건: 10/10 HTTP200, 견적 내용 10/10, 실행 메타데이터 포함 9/10.
- 남은 검증: 실제 추론 모드 전달과 완성 견적 PDF E2E.
- [독립 모델 평가 상세](B14_FINAL_GEMINI_3_5_FLASH_LITE_2026-10-09.md).

## 6. 이후 모델에도 동일하게 기록하는 형식

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

## 2026-10-09 Gemini 3.5 리즈닝 4단계 실측 완료

- 수정한 Google 직접 호출 API 키로 **40/40 HTTP 200**.
- 신규 동일 견적 10문항 × 4단계: **Minimal 10/10 (1,089ms, 382토큰), Low 8/10 (1,048ms, 382토큰), Medium 10/10 (2,362ms, 987토큰), High 9/10 (3,302ms, 1,408토큰)**. 평균 지연과 평균 총 사용 토큰은 요청당 수치.
- High QKR-008 길이 제한은 max_tokens 1,800 때문이며 4,096토큰 별도 1회에서 PASS. 합산 점수는 원래 40건 기준.
- **견적 추출 기본 리즈닝 추천: Minimal.** B14 게이트웨이에서 명시적 리즈닝 전송은 아직 미시험.
- Minimal 직접 모델 출력 → B66 QuoteCore → A4 PDF: 12개 품목·총 715만원 PASS, 하단 안내 문구 때문에 2페이지. 고객 최종 PDF E2E는 계속 진행 중.
- 상세: [Gemini 3.5 실제 리즈닝 40회 및 PDF](B14_FINAL_GEMINI_3_5_REASONING_AND_PDF_2026-10-09.md).


## 2026-10-09 Gemma 4 26B A4B 독립 최종 평가

- 공식 모델: 입력 256K, MoE 25.2B/활성 3.8B, 리즈닝 Minimal/High 두 모드. 공식 최대 출력 UNKNOWN.
- 무료 티어: 30 RPM / 입력 16,000 TPM / 14,400 RPD.
- B14 경유 QKR-001: **HTTP 504, 33.08초**. Google 직접 native QKR-001: **HTTP 200, 2.77초, 견적 정확**.
- Google 직접 20회: Minimal **8/10** (평균 3.26초·382토큰), High 엄격 JSON **0/10** (20.62초·1,208토큰). High는 JSON 형식 위반 10건 중 1건 길이 제한.
- Minimal QKR-008 AI 응답 → QuoteCore → 로컬 PDF: 12품목, 합계 **715만원** PASS. 하단 안내 문구 때문에 PDF 2페이지.
- B14 경유 연동 및 고객 저장 템플릿 PDF는 미완료.
- 모델별 상세: [Gemma 4 26B 신규 최종 평가](B14_FINAL_GEMMA_4_26B_2026-10-09.md).

## 2026-10-09 Gemma 4 31B 신규 독립 최종 평가

- 공식 API 입력 262,144, 출력 32,768, Dense 30.7B, reasoning Minimal/High.
- 무료 30 RPM/16K TPM/14,400 RPD.
- 신규 20회 직접 Google 견적 시험: Minimal 원본 1/10, 코드블록 정리 후 내용 5/10; High 원본 0/10, 코드블록 정리 후 내용 0/10.
- B14 경유 한 건 HTTP504. 고객 PDF E2E 별도 미완료.
- 상세: [Gemma 4 31B 최종 평가](B14_FINAL_GEMMA_4_31B_2026-10-09.md).

## 2026-10-09 Poolside Laguna S 2.1 — 신규 최종 평가

- 공식 Poolside API 직접 호출(비 Kilo·비 B14) 30회: **30/30 HTTP200**. 리즈닝 미지정 9/10, 추론 끄기 8/10, 추론 켜기 8/10 견적 내용 정확.
- 추론 끄기 평균 4.63초/500토큰, 켜기 9.56초/742토큰. 동일 8/10이므로 견적 정보 추출은 **추론 끄기 우선 추천**.
- B14 내 Poolside 직접 제공자 라우트 별도 10건: 9/10 HTTP200·1건 504, 정상 응답의 내용 8/9 정확, 경로 메타데이터 불일치 3건.
- 공식 118B 총·8B 활성·1M 컨텍스트. 로컬 OpenCode 설정 262,144 컨텍스트/32,768 출력 제한과 구분. 직접 계정 RPM/TPM/RPD 및 최대 출력은 미확인.
- 실제 모델 QKR-008 12품목 → B66 QuoteCore → A4 PDF 생성 PASS: 공급 650만원·부가세 65만원·합계 715만원, 2페이지 하단 안내 문구 이월.
- 상세: [Poolside Laguna S 2.1 독립 최종 평가](B14_FINAL_POOLSIDE_LAGUNA_S_2_1_2026-10-09.md).


## 2026-10-09 SenseNova 6.8 Flash Lite 독립 최종 평가

- 제공자 live metadata: 컨텍스트 **262,144**, 최대 출력 **65,536**, 이미지·텍스트 입력, reasoning/json_mode/tools 지원.
- 신규 B14 직접 SenseNova 모델 명시 선택: **10/10 엄격 PASS, HTTP200 10/10, 평균 7,125ms**.
- 제공자 직접 API 기본: **10/10 내용 정확, HTTP200 10/10, 평균 5,233ms**.
- 리즈닝 4수준 × 10개 견적: **none 10/10 2633ms; low 10/10 6528ms; medium 10/10 6278ms; high 10/10 6503ms**. 자세한 사용량·오류는 상세 문서 참조.
- 실제 모델 12품목 응답→QuoteCore→PDF: **12품목·총 715만원 PASS**, 2페이지 공통 하단 안내 문구 이월.
- 현재 연결된 SenseNova 계정의 RPM/TPM/RPD 값과 B14 리즈닝 명시적 전달은 별도 확인 대상.
- 상세: [SenseNova 6.8 Flash Lite 최종 평가](B14_FINAL_SENSENOVA_6_8_FLASH_LITE_2026-10-09.md).
