# Gemini 3.5 Flash Lite — 리즈닝 단계·견적 PDF 추가 검증 (2026-10-09)

**라운드:** B14_FINAL_MODEL_EVALUATION_2026-10-09. 기존 B66 과거 평가와 점수를 합산하지 않는다. 이 문서는 [Gemini 3.5 최종 평가](B14_FINAL_GEMINI_3_5_FLASH_LITE_2026-10-09.md)의 후속 실측 기록이다.

## 1. 리즈닝 minimal/low/medium/high 실제 호출 상태

Google [공식 Thinking 문서](https://ai.google.dev/gemini-api/docs/thinking)에서 Gemini 3.5 Flash-Lite의 지원 수준은 **minimal / low / medium / high**, 기본값은 **minimal**로 확인했다.

동일한 합성 한국어 견적 QKR 10개를 네 수준에서 각 1회 직접 실행해 정확도·지연·토큰을 비교하는 40건 시험을 준비했다. 목적은 이전 B14 10건 단회 점수와 별개의 **추론 설정별 신규 시험**이다.

**실제 결과:** Google OpenAI 호환 API에 local Gemini CLI의 기존 GEMINI_API_KEY로 직접 호출했으나, **HTTP 400 INVALID_ARGUMENT**와 제공자 진단 Please pass a valid API key가 확인됐다. 명시적 minimal 요청뿐 아니라 reasoning_effort 생략 요청도 동일한 오류를 반환했다.

| 리즈닝 | 실제 호출/판정 | 정확도 | 평균 지연 | 토큰 |
|---|---|---|---|---|
| minimal | 인증 진단 실패: HTTP 400, 유효하지 않은 로컬 키 | **측정 불가** | 측정 불가 | 측정 불가 |
| low | 미실시 — 키 오류 후 추가 대량 호출 중지 | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| medium | 미실시 — 키 오류 후 추가 대량 호출 중지 | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| high | 미실시 — 키 오류 후 추가 대량 호출 중지 | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| 옵션 생략 | HTTP 400, 로컬 키 오류 재확인 | 측정 불가 | 측정 불가 | 측정 불가 |

**판정:** 직접 Google 호출 경로의 **로컬 키가 유효하지 않아 실험 미완료**. 모델의 리즈닝 자체가 거부되거나 출력 품질이 낮다는 결론이 아니다. 정상 작동 중인 B14 Worker의 Google 연동 키와 별개인 로컬 자격증명이다. 다음 단계는 이 로컬 호출 경로에 유효한 Google AI Studio API 키를 연결하고 동일 10개 문제 × 네 리즈닝 수준으로 재실행한다. 새로운 키를 문서에 저장하거나 출력하지 않는다.

## 2. 실제 Gemini 3.5 응답 → B66 계산 → PDF 렌더링

Google B14 운영 수동 라우트 google/gemini-3.5-flash-lite로 **새 합성 견적 응답을 호출**하고, 실제 응답을 변경 없이 다음 단계에 순서대로 투입했다.

Google B14 API 응답 → B66 QuoteExtraction.normalizeExtraction / buildDraftCandidate → B66QuoteAppBridge.replaceDraft → QuoteCore.computeDraftTotals → 로컬 브라우저 A4 print PDF → pdf-lib/PyMuPDF 결과 검사.

| 항목 | QKR-001 기본 견적 | QKR-008 12개 품목 |
|---|---|---|
| Google B14 HTTP | 200 | 200 |
| AI 원문 사실 추출 | PASS | **FAIL: 프로젝트명 필드** |
| B66 추출 JSON 및 Draft 변환 | PASS | PASS |
| 화면 품목 수와 전송 품목 수 | **1/1** | **12/12** |
| QuoteCore 공급가액 | 500,000원 | 6,500,000원 |
| QuoteCore 부가세 | 50,000원 | 650,000원 |
| QuoteCore 합계 | **550,000원** | **7,150,000원** |
| 품목 계산 일치 | PASS | PASS |
| 실제 PDF 헤더 및 파일 생성 | PASS | PASS |
| 실제 PDF 페이지 수 | **1** | **2** |
| 12개 품목/금액의 PDF 텍스트 | 해당 없음 | **12개 전부 1페이지에 존재; 합계 1페이지에 존재** |
| PDF 하단 문구 | 1페이지 | **2페이지에만 남음** |

12개 품목 PDF 2페이지의 텍스트는 다음 두 문장만 나타났다: 견적 유효기간 내 발주 시 상기 금액을 적용합니다. / 세부 일정은 협의 후 확정합니다.

이는 **브라우저 PDF 렌더러의 하단 문구 페이지 넘김 문제**다. 이번 PDF는 로컬 표준 미리보기 출력으로, 로그인된 고객의 저장 CGI 인증 템플릿/클라이언트 래스터 최종 다운로드를 검증한 결과가 아니다. 고객 저장 템플릿 PDF E2E는 별도 F6 완료 조건으로 유지한다.

**반복 품질 관측:** 이번 최종 라운드 최초 10건에서는 QKR-008의 모델 내용이 맞았으나, PDF 연결을 위해 새로 호출한 QKR-008 두 차례는 모두 모델 정확도 게이트를 통과하지 못했다. 한 응답에서 회사명·발행일·품목 12개는 맞았고 **프로젝트명**이 틀린 것을 확인했다. 단회 **10/10 추출 점수는 재현성 보증이 아니다.** 반복 시험을 추가한 후 품질 판단을 내려야 한다.

## 3. 다음 완료 조건

1. **리즈닝 실제 측정:** 유효한 Google AI Studio 직접 호출 경로로 minimal·low·medium·high 각각 동일 QKR 10개, 요청 간 간격 준수, 정확도·지연·출력/추론 토큰·429/504 분리 측정.
2. **추출 정확도:** QKR-008 프로젝트명 불안정성을 문항별 재현성·지시문 점검으로 해결.
3. **PDF 레이아웃:** 12개 품목에서 하단 안내 문구가 단독으로 2페이지에 밀리지 않도록 B66 레이아웃 변경 후 동일 A4 실제 PDF로 재검증.
4. **고객용 PDF E2E:** 인증된 저장 견적 양식 선택 → 실제 AI 추출 → QuoteCore 합계 → 다운로드 PDF를 검증.

**최종 판정:** IN_PROGRESS. 모델 사양과 10회 기본 호출은 확인됨. 리즈닝 실측과 제품 CGI PDF E2E는 아직 완료하지 못했다.

로컬 합성 증거:
- E:\b14-gemini35-REASONING-DIRECT-20261009.json (직접 API 호출 HTTP400, 키 오류)
- E:\b14-gemini35-FINAL-20261009-safe-results.json (기존 이번 최종 라운드 10건)
- E:\b14-gemini35-pdf-real-fixtures-261009\rendered\QKR-001-Gemini35-QuoteCore.pdf
- E:\b14-gemini35-pdf-real-fixtures-261009\rendered\QKR-008-Gemini35-QuoteCore.pdf
