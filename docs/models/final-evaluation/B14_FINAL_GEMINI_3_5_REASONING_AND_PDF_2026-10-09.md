# Gemini 3.5 Flash Lite — 리즈닝 4단계 실제 평가 및 견적 PDF

- 라운드: B14_FINAL_MODEL_EVALUATION_2026-10-09
- 상태: 리즈닝 직접 API 실측 완료, 로컬 견적 PDF 생성 완료, 고객 저장 템플릿 E2E는 미완료
- 정확한 직접 모델: gemini-3.5-flash-lite
- 무료 티어: 15 RPM / 입력 TPM 250,000 / RPD 500 (Owner 제공 Google AI Studio 화면)

## 1. 수정된 API 키 확인

Google AI Studio OpenAI 호환 API에서 minimal 명시 요청과 리즈닝 생략 요청 모두 HTTP 200으로 성공했고 응답 모델 ID가 일치했다.

**이전 진단 해결:** 키를 수정하기 전의 HTTP 400 (Please pass a valid API key)은 로컬 키 오류였다. 당시 측정 불가였던 네 단계의 실제 성능은 아래 40회 신규 호출로 재측정했다.

## 2. 리즈닝별 견적 추출 40회 신규 측정

동일한 합성 견적 QKR-001~010을 각 리즈닝 minimal, low, medium, high에서 한 번씩 실행했다. 직접 Google API, temperature=0, max_tokens=1,800, 재시도 0, 모델 대체 0, 5.5초 이상 요청 시작 간격.

| 리즈닝 | HTTP 200 | 내용 정확도 | 평균 지연 | 평균 총 사용 토큰 | 10건 총 토큰 |
|---|---:|---:|---:|---:|---:|
| **minimal** | 10/10 | **10/10** | 1,089ms | 382 | 3,815 |
| **low** | 10/10 | **8/10** | 1,048ms | 382 | 3,821 |
| **medium** | 10/10 | **10/10** | 2,362ms | 987 | 9,870 |
| **high** | 10/10 | **9/10** | 3,302ms | 1,408 | 14,079 |

총 **40/40 HTTP 200**, HTTP 429와 504는 각 0건. 제공자 usage.total_tokens가 총 사용량의 기준이며, 제공자에서 내부 추론 토큰 상세값은 안정적으로 제공되지 않아 추론 토큰 수를 별도로 추정하지 않았다.

### 틀린 문항

- Low QKR-007: 프로젝트명(project_name) 오류, 품목은 정확.
- Low QKR-008 (12개 품목): 프로젝트명 오류, 12개 품목은 정확.
- High QKR-008: 출력 예산 1,800토큰에서 finish_reason=length, JSON 출력 미완성.

**High 출력 예산 분리 시험:** 동일 QKR-008만 max_tokens=4,096으로 별도 추가 1회 직접 호출한 결과 HTTP 200, finish_reason=stop, **정확도 PASS**, 총 2,126토큰, 4,297ms. 이 별도 시험은 동일 1,800토큰 조건의 40건 통계에는 합산하지 않았다.

### 견적 추출 기본 리즈닝 추천

**minimal 추천.** 동일 10개 문제에서 Minimal과 Medium은 모두 10/10 정확했지만, 평균 속도는 Minimal **1.09초**, Medium **2.36초**이고 총 사용 토큰도 Minimal이 적었다. Low는 약간 빠르지만 8/10 정확도라 제외, High는 더 느리고 높은 출력 예산이 필요했다.

이는 이번 합성 견적 10개에 근거한 **제품 기능별** 선정이다. 모든 종류의 작업에서 minimal이 최고라는 결론은 아니다.

## 3. 실제 모델 출력 → B66 견적 계산 → PDF

위 40건 중 **minimal QKR-008**에서 정확도 PASS였던 실제 Google 모델 응답을 B66 QuoteExtraction → QuoteDraft → QuoteCore → 브라우저 A4 PDF에 사용했다.

| 검사 | 결과 |
|---|---|
| 실제 모델 응답 QKR-008 | PASS |
| 12개 품목 표시 | 12/12 PASS |
| 공급가액 | **6,500,000원** |
| 부가세 | **650,000원** |
| 최종 합계 | **7,150,000원** |
| 계산 검증 | PASS |
| PDF 파일 생성 | PASS |
| 실제 PDF 페이지 | **2페이지** |
| 별도 B14 기본 QKR-001 로컬 PDF 관측 | 공급 500,000원, 부가세 50,000원, 합계 **550,000원**, 1페이지 PASS |
| 레이아웃 관측 | 12개 품목과 총액은 1페이지, 하단 안내 문구만 2페이지 |

기존 B14 경유의 추가 QKR-008 재호출 두 차례에서는 프로젝트명 오류가 관측됐었다. 이번 **직접 Google API 40회** 결과와 기존 B14 경유 재호출은 경로가 다르므로 점수를 혼합하지 않았다.

이번 PDF는 **로컬 브라우저 인쇄 PDF**이다. 저장된 고객 CGI 인증 양식의 최종 다운로드 E2E는 NOT_TESTED이며, B66 하단 안내 문구의 페이지 넘김 수정 후 별도 검증이 필요하다.

## 4. 이번 모델의 완료 여부

| 관문 | 상태 |
|---|---|
| F1 공식 모델 사양 | CONFIRMED |
| F2 무료 할당량 | CONFIRMED (15 RPM / 250,000 TPM / 500 RPD) |
| F3 실제 Google 직접 API 네 가지 reasoning_effort | **PASS — 40회** |
| F3 B14 운영 게이트웨이의 명시적 reasoning 전달 | **NOT_TESTED** |
| F4 직접 API 가용성 | **PASS — 40/40** |
| F5 견적 정확도 | Minimal 10/10, Low 8/10, Medium 10/10, High 9/10 |
| F6 실제 모델 응답으로 로컬 PDF 생성 | PASS, 12품목 2페이지 |
| F6 고객 저장 양식 PDF E2E | **NOT_TESTED** |
| 최종 제품 판정 | **IN_PROGRESS** |

실측 자료 (로컬):
- E:/b14-gemini35-REASONING-DIRECT-20261009-AFTER-KEY-FIX.json
- E:/b14-gemini35-QKR008-RENDER-INPUT-20261009.json
- E:/b14-gemini35-pdf-minimal-final-261009/rendered/QKR-008-Gemini35-QuoteCore.pdf
