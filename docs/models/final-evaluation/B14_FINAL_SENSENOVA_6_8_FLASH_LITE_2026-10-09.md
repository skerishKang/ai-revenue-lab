<!-- B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->
> **2026-10-10 최신 해석:** [B14 공식 파라미터·재시험 판단 감사](B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md)를 먼저 확인하세요. 아래 과거 실측·우열·추천은 **기록 당시 파라미터에서의 결과**로만 유지합니다. 기존 평가에서 사용한 temperature=0 및 공통 max_tokens는 공식 권장 설정으로 간주하지 않습니다. 공식 공급사 기본값/추론/출력 예산을 검증하는 별도 재시험과 B14 전달 검증 전에는 최종 성능 우열로 사용하지 않습니다. 모델 자동 선택, 대체 라우팅 또는 운영 배포를 승인하는 문서가 아닙니다.
<!-- /B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->

# B14 최종 모델 평가 — SenseNova 6.8 Flash Lite

**라운드:** B14_FINAL_MODEL_EVALUATION_2026-10-09
**기록일:** 2026-10-09
**B14 선택 ID:** `sensenova/sensenova-6.8-flash-lite`
**제공자 실제 모델 ID:** `sensenova-6.8-flash-lite`
**상태:** 모델 직접 호출·리즈닝 4수준·B14 실측·로컬 PDF 검증 완료. B14 리즈닝 명시 전달 및 고객 저장 양식 최종 PDF E2E 별도 미검증.

## F1 — 공식 사양 / 연결된 제공자 실조회

SenseNova 공식 API 문서: https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md

실제 연결된 제공자의 GET https://token.sensenova.ai/v1/models 반환값(HTTP200)을 조회해 아래와 같이 확정.

| 속성 | 값 / 검증 |
|---|---|
| 모델 ID | `sensenova-6.8-flash-lite` |
| 컨텍스트 길이 | **262,144토큰** |
| 제공자 API가 반환한 최대 출력 | **65,536토큰** |
| 입력 | 텍스트·이미지 |
| 출력 | 텍스트 |
| 지원 기능 | 도구 호출, JSON 모드, 리즈닝 |
| 실제로 수락된 추론 제어 | `reasoning_effort=none/low/medium/high` |
| 공식 `max_tokens` 의미 | 최종 출력뿐 아니라 추론 토큰까지 포함한 요청 출력 예산 |
| B14 제품 코드에 명시적 설정 가능한 `max_tokens` | **1~4,096** (모델 자체 한도와 별도) |
| 본 비교의 모델 출력 예산 | **1,800토큰/요청** |

현재 사용 중인 제공자 주소는 `https://token.sensenova.ai/v1`. 공식 공개 문서 예시에는 `https://token.sensenova.cn/v1`이 사용되지만, 이번 실호출은 연결된 **.ai** 제공자 엔드포인트에서 검증했다. 두 지역 도메인에 동일한 계정 제한이 적용된다고 단정하지 않는다.

## F2 — 연결 계정의 할당량

| 구분 | 현재 확인된 사실 |
|---|---|
| 실제 계정 플랜 | **UNKNOWN** |
| RPM | **UNKNOWN** |
| 입력 TPM | **UNKNOWN** |
| RPD | **UNKNOWN** |
| 이번 실측의 API 429 | 평가에 기록된 건수만 판정 |
| 제원과 계정 할당량의 구분 | 262,144/65,536은 모델 용량이고 RPM/TPM/RPD가 아님 |

**SenseNova의 연결된 계정 플랜·할당량은 API 모델 목록에 없으므로 임의 숫자를 기재하지 않는다.**

## F3–F5 — 견적 추출 새 최종 라운드 실측

실험 입력: B66과 동일 합성 한국어 견적 QKR-001~QKR-010, 원본 Prompt/정답 고정, temperature=0, max_tokens=1,800. 동일 케이스·리즈닝 조합은 1회만 호출, 재시도와 fallback 없음.

### A. B14 Worker 경유 (수동 지정 모델)

| 항목 | 새 시험 결과 |
|---|---|
| B14 선택 모델 | `sensenova/sensenova-6.8-flash-lite` |
| HTTP200 | **10/10** |
| 견적 내용+실제 경로 검증 엄격 통과 | **10/10** |
| 평균 응답 시간 | **7,125ms** |
| 평균 총 토큰 | **833** |
| HTTP429/504 | **0/0** |
| 명시적 reasoning_effort 전달 검증 | **NOT_TESTED** (현 B14 요청은 리즈닝 수준 지정하지 않음) |

### B. 공식 SenseNova 직접 API (B14 우회, 설정 미지정)

| 항목 | 새 시험 결과 |
|---|---|
| HTTP200 | **10/10** |
| 견적 내용 정확 | **10/10** |
| 평균 응답 시간 | **5,233ms** |
| 평균 총 토큰 | **784** |
| 추론 본문 필드 포함 | **10/10** |
| 엔드포인트 | `token.sensenova.ai/v1/chat/completions` |

### C. 제공자 직접 API — 동일 10문항 × 4단계 = 40회

| 리즈닝 | HTTP200 | 견적 내용 PASS | 평균 지연(ms) | 평균 총 토큰 | 추론 필드 존재 |
|---|---:|---:|---:|---:|---:|
| **none** | 10/10 | **10/10** | 2,633 | 428 | 0/10 |
| **low** | 10/10 | **10/10** | 6,528 | 832 | 10/10 |
| **medium** | 10/10 | **10/10** | 6,278 | 795 | 10/10 |
| **high** | 10/10 | **10/10** | 6,503 | 812 | 10/10 |

실험 전체 40건의 HTTP429/504는 각각 **0/0**.

**실험 실패 사례 (사실/JSON/출력 제한별 구분):**
- none: 없음 (10/10 견적 내용 정확)
- low: 없음 (10/10 견적 내용 정확)
- medium: 없음 (10/10 견적 내용 정확)
- high: 없음 (10/10 견적 내용 정확)

**리즈닝 설정 판정 기준:** `none`에서는 응답의 `message.reasoning` 필드가 존재하지 않고 다른 수준에서 존재하는지 및 사용량·지연이 달라지는지를 함께 점검했다. 단순 HTTP200만으로 설정이 실제 작동했다고 판정하지 않는다.

### 견적 추출 제품 선택 기준

- 동일 정확도라면 더 낮은 지연·토큰을 사용한 리즈닝 수준을 우선 추천.
- 출력 `length` 종료의 경우 추론 자체의 정보 오류와 `max_tokens=1800` 예산 부족을 분리 판정.
- 10문항은 초기 제품 적합성 테스트이므로 장기 재현성·일반 대화 능력을 확정하지 않는다.

## F6 — 실제 모델 응답 → B66 견적 계산 → A4 PDF

직접 API QKR-008(12개 품목)의 실제 정확도 PASS 응답을 다음 구성 요소에 투입했다.

`SenseNova 실제 JSON → B66 QuoteExtraction → QuoteDraft → QuoteCore.computeDraftTotals → Chromium 로컬 A4 PDF`

| 검증 항목 | 결과 |
|---|---|
| AI 추출 내용 정답 비교 | PASS |
| 실제 견적 화면의 품목 | **12/12** |
| 공급가액 | **6,500,000원** |
| 부가세 | **650,000원** |
| 총액 | **7,150,000원** |
| QuoteCore 품목·금액 산식 | PASS |
| 실제 PDF 생성 및 바이트 검사 | PASS |
| PDF 본문 검사 | 1페이지에 12품목 전부와 합계 715만원 |
| PDF 페이지 수 | **2페이지**, 2페이지에는 하단 안내 문구 48문자만 존재 |
| 고객 저장 CGI 템플릿 최종 PDF 다운로드 | **NOT_TESTED** |

이번 로컬 브라우저 인쇄 PDF는 제품의 최종 저장 CGI PDF E2E와 구분한다. 하단 안내문구만 2페이지로 넘어가는 현상은 다른 평가 모델에서도 재현된 공통 B66 레이아웃 이슈다.

## F1–F6 게이트 판정

| 게이트 | 상태 |
|---|---|
| F1 공식 모델 사양/제공자 live metadata | CONFIRMED |
| F2 실제 계정 RPM/TPM/RPD | UNKNOWN |
| F3 직접 API reasoning_effort 4단계 | COMPLETE (위 결과 참조) |
| F3 B14 라우터에서 선택된 reasoning 전달 | NOT_TESTED |
| F4 B14 신규 API 요청 | **10/10 HTTP200** |
| F4 직접 API 요청 | **10/10 HTTP200 + 40건 추가 비교** |
| F5 사실 추출 정확도 | 위 표의 라우트·리즈닝별 점수 |
| F6 실제 AI 데이터 → 로컬 PDF | **PASS**, 공통 2페이지 레이아웃 |
| F6 고객 저장 양식 PDF | NOT_TESTED |
| 제품 최종 승인 | **IN_PROGRESS** |

**데이터 증거:** `E:\b14-sensenova68-FINAL-20261009-safe-results.json`; `E:\b14-sensenova68-DIRECT-10QKR-20261009.json`; `E:\b14-sensenova68-DIRECT-REASONING-40QKR-20261009.json`; `E:\b14-sensenova68-PDF-20261009\rendered\QKR-008-SenseNova68-QuoteCore.pdf`.
