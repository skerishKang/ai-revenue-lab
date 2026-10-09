# B14 최종 모델 평가 — Poolside Laguna S 2.1 (직접 API)

- **평가 라운드:** `B14_FINAL_MODEL_EVALUATION_2026-10-09`
- **평가일:** 2026-10-09 KST
- **B14 등록 ID / 상류 ID:** `poolside/laguna-s-2.1`
- **실제 직접 제공자:** `https://inference.poolside.ai/v1`
- **결론:** 견적 내용 추출 능력 양호, 견적 작업에서는 추론 끄기 우선 추천. **최종 제품 승인 IN_PROGRESS**.
- **구분:** 직접 Poolside API는 **Kilo Gateway Laguna가 아니다**. B14 경유 시험도 명시적 Poolside 직접 제공자 라우트이며, Kilo를 사용하지 않았다.

## F1 — 공식 모델 사양과 로컬 프로필

| 속성 | 확인 결과 |
|---|---|
| 모델 구조 | 118B 총 파라미터 / 활성 8B MoE |
| 공식 발표 컨텍스트 | 약 1M tokens (Poolside 공식 발표) |
| 타 제공자(Vercel Gateway) 표시 최대 출력 | 131,072 tokens — **Vercel 제공 경로 값**으로 구분 |
| OpenCode 로컬 프로필 | 컨텍스트 **262,144**, 최대 출력 **32,768** (로컬 설정값) |
| 현행 B14 모델 레지스트리 | 컨텍스트 1,000,000 (표시·메타데이터) |
| 직접 Poolside 계정에서 실제 허용되는 최대 출력 | **UNKNOWN**, 이번 평가에서는 1,800토큰 출력 예산 사용 |
| 리즈닝 제어 | `chat_template_kwargs.enable_thinking=true/false` — 공식 모델 카드 안내·실제 두 모드 호출 확인 |
| 입력/출력 | 텍스트 입력·텍스트 출력; 코딩 에이전트 특화 |

공식 근거:
- [Poolside 모델 안내](https://poolside.ai/models)
- [Poolside Laguna S 2.1 발표](https://poolside.ai/blog/introducing-laguna-s-2-1)
- [Poolside 모델 카드, reasoning 제어](https://huggingface.co/poolside/Laguna-S-2.1)
- [Vercel Gateway 출력 한도(해당 경로만)](https://vercel.com/ai-gateway/models/laguna-s-2.1)

**프로필 판단:** 다른 제공자의 최대 출력과 로컬 `limit.output`은 동일한 제한이 아니다. B14 기본 출력 예산을 공식 이론값으로 무조건 확대하지 않고, Poolside 직접 제공자에서 적용 가능한 최대값은 별도로 실측한다.

## F2 — 실제 Poolside 계정 한도

| 한도 | 현재 증거 |
|---|---|
| 유료/무료 등급 | `UNKNOWN` — 로컬 직접 키로 실제 호출 성공, 계정 티어 별도 미조회 |
| RPM | `UNKNOWN` |
| 입력 TPM | `UNKNOWN` |
| RPD | `UNKNOWN` |
| 이번 실제 견적 요청에서 429 | 직접 API **0건/30회** |

Google AI Studio의 무료 RPM·TPM·RPD 값은 Poolside에 적용하지 않는다. 실제 성공 수는 호출 가능성의 증거이지 공식 계정 제한값은 아니다.

## F3–F5 — 동일 견적 10문항 실제 성능

합성 견적 정답 QKR-001~QKR-010과 **완전히 동일한 프롬프트·정답 기준**으로 평가. `temperature=0`, `max_tokens=1800`, 명시 모델 고정, 요청당 1회, 재시도 0, fallback 0.

### ① 공식 Poolside 직접 API — B14·Kilo 모두 우회

| 설정 | HTTP 200 | 견적 내용 PASS | 평균 응답 | 평균 총 토큰 |
|---|---:|---:|---:|---:|
| 리즈닝 옵션 생략 | **10/10** | **9/10** | **10.89초** | **782** |
| **명시적 추론 끄기** (`enable_thinking=false`) | **10/10** | **8/10** | **4.63초** | **500** |
| 명시적 추론 켜기 (`enable_thinking=true`) | **10/10** | **8/10** | **9.56초** | **742** |

각 설정별로 QKR 10건을 별도로 전송했다. **직접 API 견적 요청 전체 30회 HTTP 200**, 429·504는 0건. 리즈닝을 끄는 경우 추가 추론 출력 필드가 10건 모두 없었고, 켜는 경우 10건 중 7건에 존재했다. 추론 옵션의 실제 효과가 사용량·지연 및 응답 필드에서 확인됐다.

- 옵션 생략: QKR-007에서 프로젝트명과 일부 품목 내용이 정답과 불일치. 나머지 9건 PASS.
- 추론 끄기: QKR-007 프로젝트명 오류, QKR-009 품목 오류로 8/10 PASS.
- 추론 켜기: QKR-007·QKR-009 품목 오류로 8/10 PASS.
- **견적 작업 기본 설정 권고:** `enable_thinking=false`. 명시적 두 모드의 정확도 8/10은 동일한데 추론 끄기가 더 빠르고 토큰 소모가 적었다. 옵션 생략의 9/10은 **별도 실행 표본**이므로 끄기보다 본질적으로 정확하다고 단정하지 않는다.

**출력 데이터 검증:** Windows PowerShell 5.1의 응답 저장 과정에서 한글 UTF-8 바이트를 Latin-1로 해석한 수집 문제가 나타났다. 저장된 모델 응답은 역변환으로 원래 UTF-8을 손실 없이 복원한 후 동일한 B66 정답 검사기에 넣었다. 수집 도구의 문자 인코딩 오류는 모델 추출 오류에 포함하지 않았다.

### ② 운영 B14 경유의 직접 Poolside 제공자 라우트 (Kilo 아님)

| 항목 | 이번 신규 10건 결과 |
|---|---|
| HTTP200 | **9/10** |
| HTTP504 | **1/10** (QKR-006 upstream_timeout) |
| 정상 응답의 견적 내용 정확도 | **8/9** |
| 실행 경로 메타데이터 포함 엄격 통과 | **5/10** |
| 메타데이터 검증 불일치 | QKR-001, QKR-002, QKR-007 — 내용은 PASS |
| 실제 내용 오류 | QKR-009 품목 |
| 정상 응답 평균시간 | **10.83초** |

**분리 판정:** 공식 Poolside 직접 API는 10/10 성공했지만 B14 경유 라우트에서 504가 발생했다. 메타데이터 불일치 3건은 콘텐츠 품질 실패와 별도로 진단한다. 원인은 미확정이며 Kilo Laguna와 혼동하지 않는다.

## F6 — 실제 Poolside 모델 응답 → B66 계산 → PDF

공식 Poolside 직접 API에서 **정답 PASS인 QKR-008(12개 품목)**의 합성 JSON을 B66 QuoteExtraction → QuoteDraft → QuoteCore → Chromium A4 PDF 렌더러로 연결.

| 항목 | 관측 |
|---|---|
| 실제 모델 추출 검증 | **PASS** |
| QuoteDraft 생성·화면 품목 | **12/12 PASS** |
| 공급가액 | **6,500,000원** |
| 부가세 | **650,000원** |
| 합계 | **7,150,000원** |
| QuoteCore 계산 | **PASS** |
| 로컬 A4 PDF 생성 | **PASS** |
| PDF 페이지 수 | **2** — 하단 안내 문구만 다음 페이지로 넘어감 |
| 고객 저장 CGI 인증 양식 최종 PDF 다운로드 | **NOT_TESTED** |

로컬 인쇄 PDF 시험은 완료됐지만 고객 저장 양식과 현재 B66 최종 렌더 엔진의 제품 승인까지 대체하지 않는다.

## 모델별 최종 결론

| 관문 | 상태 |
|---|---|
| F1 공식 모델 능력 | CONFIRMED, 직접 API 최대 출력 상한은 별도 확인 필요 |
| F2 Poolside 실제 계정 RPM/TPM/RPD | UNKNOWN |
| F3 직접 hosted thinking on/off | **PASS (명시 20회, 응답과 usage 비교)** |
| F3 B14 reasoning 설정 전달 | NOT_TESTED |
| F4 직접 API 가용성 | **PASS (30/30 HTTP 200)** |
| F4 B14 Poolside 직접 제공자 라우트 | **9/10 HTTP 200, 1건 HTTP504** |
| F5 견적 정확도 | **기본 9/10, 추론 끄기 8/10, 켜기 8/10** |
| F6 AI → QuoteCore → 로컬 PDF | PASS, 공통 페이지 넘김 문제 |
| F6 고객 저장 템플릿 PDF | NOT_TESTED |
| **제품 최종 승인** | **IN_PROGRESS** |

**선정 비교:** Gemini 3.5 Flash Lite Minimal은 동일 견적 10문항에서 10/10·평균 1.09초. Laguna S 2.1도 직접 API에서 내용 정확성이 높지만 속도·일관성 면에서 B66 견적 추출 1순위로 바꿀 근거는 아직 없다. 다만 별도 코딩 에이전트 성능은 이번 견적 평가로 판정하지 않는다.

로컬 증거(현재 대화에서는 파일 배포 없이 경로만 기록):
- `E:\b14-poolside-direct-identical-qkr-261009\SAFE_EVALUATION_METRICS.json`
- `E:\b14-poolside-direct-identical-qkr-261009\REASONING_TWO_MODES_SAFE_RESULTS.json`
- `E:\b14-poolside-B14-DIRECT-20261009-safe-results.json`
- `E:\b14-poolside-quote-pdf-261009\rendered\QKR-008-PoolsideLaguna-QuoteCore.pdf`
