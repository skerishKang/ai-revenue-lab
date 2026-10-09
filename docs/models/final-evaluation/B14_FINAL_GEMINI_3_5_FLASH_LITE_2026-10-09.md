# B14 최종 모델 평가 — Gemini 3.5 Flash Lite

평가 라운드: B14_FINAL_MODEL_EVALUATION_2026-10-09
상태: IN_PROGRESS — F1/F2 완료, F4/F5 신규 시험 완료, F3 명시적 추론·F6 실제 PDF 최종 검증 예정
평가 대상 B14 ID: google/gemini-3.5-flash-lite
정확한 Google upstream: gemini-3.5-flash-lite

## F1 공식 모델 사양

| 항목 | 공식 값 |
|---|---|
| 입력 컨텍스트 | **1,048,576토큰** |
| 모델 이론적 최대 출력 | **65,536토큰** |
| 추론 수준 | **minimal / low / medium / high** |
| 기본 추론 | **minimal** |
| Google 기본 요청 필드 | thinking_level |
| Google OpenAI 호환 필드 | reasoning_effort |
| 입력 유형 | 텍스트·이미지·영상·오디오·PDF |
| 출력 유형 | 텍스트 |

공식 근거:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/thinking
- https://ai.google.dev/gemini-api/docs/openai

## F2 실제 Google AI Studio 무료 티어 (Owner가 제공한 2026-10-09 화면)

| RPM | 입력 TPM | RPD |
|---:|---:|---:|
| **15** | **250,000** | **500** |

최대 출력 65,536은 모델 능력이고, 250,000 TPM은 무료 프로젝트의 분당 입력량이다. 이번 견적 추출 시험은 요청별 최대 출력 1,800토큰으로 시행했다.
전체 무료 할당량 자료: [AI Studio 모델별 한도표](GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.md).

## F3 모델 설정 검증 기준

현재 공식 사양으로 이번 모델의 입력/출력/리즈닝 프로필을 확정한다. 실제 추론 단계 시험에서는 minimal, low, medium, high, 리즈닝 생략을 각각 독립 검증해 출력 토큰 사용량, 유효 응답, 완료 이유와 지연을 기록한다. 별도 모델의 설정 변경이나 자동 모델 대체는 평가에 포함하지 않는다.
현재 단계의 검증: **F1 공식 설정값 조사 완료, F3 실제 명시적 리즈닝 요청 시험은 미실시**.

## F4–F5 새 최종 라운드의 실제 견적 시험

이 모델을 명시 선택해 합성 QKR-001~010을 각 1회 실제 B14 요청했다. 기존 B66 평가의 점수는 이 결과에 섞지 않았다. 호출 시작 간 최소 8초 간격, 자동 재시도 0, 자동 fallback 0.

| 항목 | 실측 결과 |
|---|---|
| 신규 API 요청 | **10회** |
| HTTP 200 / 429 / 504 | **10 / 0 / 0** |
| 내용 정확도(회사명·프로젝트·날짜·품목) | **10/10** |
| 정확한 실행 경로 메타데이터까지 포함 | **9/10** |
| QKR-008 | 12개 품목 내용은 모두 정확, 실행 경로 메타데이터 1회 불일치 |
| 최소 / 평균 / 최대 응답시간 | **1,452 / 4,837 / 14,187ms** |
| 평가 입력 방식 | 최대 출력 1,800토큰, temperature=0, 합성 입력 |

QKR-008의 메타데이터 불일치는 실제 모델 자동 대체가 있었다는 증거로 해석하지 않는다. **추출 능력 10/10과 실행 경로 검증 9/10을 분리**한다.

### 케이스별 내역

| 케이스 | HTTP | 내용 정확도 | 경로 메타데이터 | 지연(ms) |
|---|---:|---|---|---:|
| QKR-001 | 200 | PASS | PASS | 2,437 |
| QKR-002 | 200 | PASS | PASS | 7,842 |
| QKR-003 | 200 | PASS | PASS | 7,656 |
| QKR-004 | 200 | PASS | PASS | 1,452 |
| QKR-005 | 200 | PASS | PASS | 1,842 |
| QKR-006 | 200 | PASS | PASS | 1,610 |
| QKR-007 | 200 | PASS | PASS | 1,610 |
| QKR-008 | 200 | PASS | NEEDS_DIAGNOSIS | 14,187 |
| QKR-009 | 200 | PASS | PASS | 2,360 |
| QKR-010 | 200 | PASS | PASS | 7,375 |

## 최종 판정과 후속 시험

| 관문 | 판정 |
|---|---|
| F1 모델 사양 | CONFIRMED |
| F2 무료 사용량 | CONFIRMED_FROM_OWNER_AI_STUDIO_SNAPSHOT |
| F3 명시적 추론 단계 실제 전달 | NOT_TESTED |
| F4 API 응답 | PASS — 10/10 HTTP200 |
| F5 견적 내용 추출 | PASS — 10/10 CONTENT; 경로 포함 9/10 |
| F6 완성 견적 PDF | NOT_TESTED — 레이아웃 정비 후 진행 |
| 최종 모델 판정 | IN_PROGRESS |

로컬 실측 근거: E:14-gemini35-FINAL-20261009-safe-results.json

## 2026-10-09 반복 추출·리즈닝·PDF 후속 실측

- 공식 지원 리즈닝 4단계 확인. 실제 직접 API에서는 로컬 Gemini 키가 유효하지 않아 HTTP400, 네 단계 성능 비교 아직 미완료.
- 신규 B14 연결 시험에서 1품목 PDF: 1페이지, 공급 500,000원·VAT 50,000원·합계 550,000원 PASS.
- 신규 B14 연결 시험에서 12품목 PDF: 품목 12개와 합계 7,150,000원 모두 첫 페이지에 포함, 안내 문구 두 줄만 두 번째 페이지로 분리됨. PDF 인쇄 레이아웃 개선 필요.
- 12품목 QKR-008 재호출에서는 프로젝트명 오류가 재현돼 최초 10/10 단회 정확도가 지속적으로 보장되지는 않음.
- [실제 리즈닝/견적 PDF 후속 결과](B14_FINAL_GEMINI_3_5_REASONING_AND_PDF_2026-10-09.md). 최종 제품 합격은 아직 IN_PROGRESS.
