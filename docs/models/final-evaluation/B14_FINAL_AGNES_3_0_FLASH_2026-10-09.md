# B14 신규 최종 모델 평가 — Agnes AI 3.0 Flash

**독립 라운드:** `B14_FINAL_MODEL_EVALUATION_2026-10-09`
**평가일:** 2026-10-09 (KST)
**선택한 B14 모델:** `agnes-ai/agnes-3.0-flash`
**제공자 실제 모델:** `agnes-3.0-flash`
**최신 Owner 판정 (2026-10-09): ERROR_B14_HTTP429 / DEFERRED / 후순위(9번)** — 운영 B14의 짧은 대화·견적 추출 모두 실패하므로 평가를 중단하고 Mercury 2.5로 순서를 넘긴다. 이전 관측 시점의 진행 상태는 아래 증거에 보존한다. 최종 승인 아님.

**판정:** **IN_PROGRESS / RATE_LIMIT_BLOCKED** — 모델 품질과 B14 운영 가용성을 구분한다. 제품 최종 승인 아님.

## F1 — 공식 사양 (2026-10-09 확인)

출처: [Agnes 3.0 Flash 공식 개발자 문서](https://www.agnes-ai.com/en/docs/agnes-30-flash).

| 속성 | 공식 문서 / 검증 |
|---|---|
| Production API 모델 ID | `agnes-3.0-flash` |
| 국제 API | `https://apihub.agnes-ai.com/v1` |
| 텍스트 채팅 | `POST /v1/chat/completions` (Responses/Messages도 문서화) |
| 컨텍스트 | **512K 토큰** |
| 최대 출력 | **65,536토큰** |
| 입력 / 출력 | 텍스트·이미지 URL / 텍스트 |
| 지원 기능 | tool calling, streaming, Thinking |
| 공식 Thinking 제어 | `chat_template_kwargs.enable_thinking=true/false` |
| API 공개 요금 | 입력 $0.05/100만 토큰, 출력 $0.15/100만 토큰의 표기가 있으나 현재 표시 요금은 모두 $0. 계정·시점별 청구 사실은 미확인 |
| B14 현재 명시적 `max_tokens` 상한 | **4,096** (B14 제품 코드; 모델 자체 65,536과 별개) |

**주의:** 공개 가중치 Preview 체크포인트의 사양을 Production/API 사양으로 옮겨 적지 않았다. 공식 Production API 문서를 우선했다.

## F2 — 연결·계정 할당량

- B14 source 단일 등록부: provider `agnes-ai` enabled, exact 모델 등록 enabled 확인.
- 배포된 B14 GET `/api/pilot/health`: `registered=true`, `has_key=true`, `mode=b14-live`.
- 배포 GET `/api/pilot/models`: 전체 9개 exact ID가 로컬 소스와 일치.
- 별도 로컬 Agnes 계정의 **직접 GET `/v1/models` HTTP200**. 전체 목록 12개 중 exact `agnes-3.0-flash` 존재.
- 실제 연결 계정의 **RPM/TPM/RPD/잔여 크레딧/플랜 UNKNOWN**. 공개 일반 한도를 현재 계정에 그대로 적용하지 않는다.
- 각 실측 채널에서 HTTP429를 별도 관측했으며 quota 제한의 원인이나 갱신 시점은 확정하지 못했다.

## F3 — 파라미터 및 라우터 계약

- 2026-10-09 B14 `gateway.py` 허용 필드 목록에는 `reasoning_effort`, `chat_template_kwargs`가 **없다**. `platform.py`의 제공자 POST body도 모델·메시지·temperature·max_tokens만 구성한다.
- 따라서 **B14를 통해 Thinking On/Off가 전달된 것으로 주장하지 않는다**. 직접 API로만 두 모드를 실측했다.
- 직접 API의 요청은 동일 고정 QKR 문항, temperature=0, max_tokens=1,800, no fallback/no retry, `enable_thinking=false/true`; 응답의 추론 필드 존재와 실제 토큰·지연시간을 함께 확인했다.
- B14 모델 선택은 명시적 exact ID만 사용하고 자동 모델 선택/대체 없음.

## F4–F5 — 견적 정보 추출 실제 API 평가

합성 한국어 견적 원본 `QKR-001..010`, 동일 `PROMPT_HEADER`, 고정 정답, 엄격 JSON 필드·12품목 포함 전체 구조 검사. 원본 키·원문 응답은 로그나 GitHub에 저장하지 않았다.

| 실행 경로 / 설정 | 시도 | HTTP200 | 견적 정답 | 평균 지연 | 평균 총 토큰 | 429 | 504 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **B14 exact 수동 경유, 기본** | 1/10 | 0 | **평가 불가** | — | — | 1 | 0 |
| **Agnes 직접 API, 기본** | 10/10 | 10 | **8/10** | **3,569ms** | **477** | 0 | 0 |
| 직접 API, **Thinking Off** | 6/10 | 5 | **5/5 응답 중 PASS** | **2,563ms** | **399** | 1 | 0 |
| 직접 API, **Thinking On** | 5/10 | 5 | **5/5 응답 중 PASS** | **7,053ms** | **717** | 0 | 0 |

**중단 조건:** B14 첫 시도 QKR-001 `HTTP429 / upstream_rate_limited` — 추가 9회 시도하지 않음. 직접 API 기본 10회는 별도 실측으로 완료. Thinking 비교는 11번째 호출(Thinking Off, QKR-006)에서 HTTP429, 즉시 중단. **429를 내용 부정확도로 채점하지 않는다.**

**직접 API 기본 모드 정확도 실패:** QKR-004, QKR-007의 `project_name` 필드 불일치. 둘 다 JSON 자체는 유효하고 품목 수와 품목별 검사 PASS, finish_reason=stop. 정확도 8/10을 가용성 10/10과 혼동하지 않는다.

**Thinking 기능 관측:** 5개씩 완료한 모드의 HTTP200 응답은 Thinking Off에서 추론 본문 없음, Thinking On에서는 추론 본문 존재. 두 모드의 해당 부분집합 모두 내용 PASS. **Thinking Off는 이번 완료된 견적 부분집합에서 속도·토큰 효율 우수**하므로 *잠정 권장*하되 10개 전체 결과로 일반화하지 않는다. `reasoning_effort=low/medium/high`은 이번 연결 계정에서 별도 검증하지 않았으므로 지원 여부를 단정하지 않는다.

## F6 — 실제 Agnes 응답 → B66 QuoteCore → A4 PDF

Agnes 직접 API에서 **QKR-008 실제 정확도 PASS**가 나온 추출 JSON을 다음 경로에 투입했다.

`Agnes actual QKR-008 JSON → QuoteExtraction.buildDraftCandidate → QuoteDraft → QuoteCore.computeDraftTotals → Chromium PDF`

| 검증 | 결과 |
|---|---|
| 실제 AI 추출 | QKR-008 PASS |
| 견적 품목 | **12/12** |
| 공급가액 | **6,500,000원** |
| 부가세 | **650,000원** |
| 총액 | **7,150,000원** |
| 금액 산식 / HTML 미리보기 | PASS / 12품목 전부 표시 |
| PDF 바이트 확인 | **PASS**, 133,454 bytes |
| PDF 본문 페이지 검사 | **2페이지**: 1페이지 564자(금액·품목 포함), 2페이지 하단 안내 문구 48자 |
| 고객 저장 양식 → 인증된 최종 PDF 다운로드 E2E | **NOT_TESTED** |

2페이지 문제는 타 모델에서도 같은 B66 레이아웃에서 재현된 페이지 나눔 현상이다. Agnes 모델 오류로 분류하지 않는다.

## 6개 게이트와 최종 판단

| 관문 | 상태 |
|---|---|
| F1 공식 모델 사양 | CONFIRMED (Production 공식 문서) |
| F2 연결 계정 별 실제 RPM/TPM/RPD | UNKNOWN, API 429 관측 |
| F3 B14 Thinking 전달 | NOT_SUPPORTED_CURRENT_REQUEST_SCHEMA |
| F3 Agnes 직접 API Thinking Off/On | PARTIAL 5/5+5/5, 429로 조기 중단 |
| F4 B14 견적 실서비스 | BLOCKED_HTTP429 1/1 (나머지 9 미시도) |
| F4 직접 API | 10/10 HTTP200 |
| F5 기본 견적 정확도 | **8/10**, 2개 프로젝트명 필드 불일치 |
| F6 로컬 QuoteCore PDF | PASS, 공통 2페이지 문제 |
| F6 고객 저장 최종 PDF E2E | NOT_TESTED |
| **제품 최종 승인** | **IN_PROGRESS**, 미승인·미병합·미배포 |

**다음 조치:** B14 제공자 키의 사용량/제한과 429 원인·갱신 시점 확인 → 허용 범위에서 미측정 문항 재평가 → 2개 프로젝트명 오류 원인 검토 → B14 리즈닝 사용자 선택 기능(#3906) 별도 승인 후 구현 → 고객 저장 PDF E2E. 계정 한도를 임의 추정하거나 무단 반복 POST하지 않는다.

## 실측 증거 파일 (원격 작업 장치 로컬, Git에 첨부하지 않음)

- `E:\b14-agnes30-FINAL-20261009-safe-results.json` (B14 429)
- `E:\b14-agnes30-DIRECT-10QKR-20261009.json` (직접 API 10문항)
- `E:\b14-agnes30-DIRECT-THINKING-20QKR-20261009.json` (11/20 수행 중 429 중단)
- `E:\b14-agnes30-PDF-20261009\rendered\QKR-008-Agnes30-QuoteCore.pdf` (PDF 2페이지)

독립 라운드 외 B66 과거 벤치마크 점수는 이 표에 이월하지 않았다.

## 2026-10-09 추가 확인 — 12분 휴지 후 B14/직접 API 1회씩 재검증

**목적:** 10 RPM 같은 단순 분당 호출 한도만으로 B14 최초 429 현상을 설명할 수 있는지 검증. 평가 모델은 계속 사용자가 명시한 `agnes-ai/agnes-3.0-flash` 한 가지로 고정.

- 마지막 로컬 Agnes 추론 평가 증거 기록부터 **약 12.6분 경과** 확인 (19:59:59 KST → 약 20:12 KST). 이 간격은 **이번 평가 스크립트 기록 기준**이며, 계정의 모든 가능한 외부 트래픽 부재를 증명하지 않는다.
- B14 GET preflight: 배포 9개 모델 ID와 소스 일치, `agnes-ai` registered/has_key, `b14-live` 확인.
- B14 `POST /api/pilot/v1/chat/completions` **QKR-001 정확히 1회**, `max_retries=0`, `max_attempts=1`, `allow_external_fallback=false`, `temperature=0`, `max_tokens=1800`: **HTTP429**, `upstream_rate_limited`, **1,266ms**, 추가 요청 0.
- 직후 로컬의 직접 제공자 `POST https://apihub.agnes-ai.com/v1/chat/completions` **QKR-001 정확히 1회**, 동일한 정답용 원문·temperature·max_tokens 및 `agnes-3.0-flash`: **HTTP200**, 엄격 견적 내용 **PASS**, 반환 모델 ID 일치, **3,609ms / 466 총 토큰**.
- **실측 판단:** 관측된 평가 요청의 단순 60초 RPM 초과만으로 두 경로의 차이를 설명하기 어렵다. B14의 429는 유지되며 로컬 직접 호출은 성공했다. B14 Secret과 로컬 키의 동일성·키별 한도·계정 플랜·사용량·제공자 출발지 정책은 **미확인**. 같은 키/계정이라고 단정하지 않는다.
- B14가 제공자의 원본 HTTP429 상세 사유 및 Retry-After를 평가 응답에 보존하지 않으므로 `upstream_rate_limited` 하나만으로 세부 제한 원인을 특정할 수 없다.
- **다음 진단 우선순위:** Agnes 관리 콘솔에서 **B14용 API 키**와 로컬 키의 계정·키 유형·쿼터 상태를 값 노출 없이 각각 비교. 필요 시 제공자 지원팀에 실제 실패 시각과 요청 ID 등 비밀이 아닌 정보로 문의. 코드·Secret 변경, 무단 배포, 추가 POST 없이 우선 확인.

로컬 증거: `E:\b14-agnes30-RPM-ISOLATED-ONE-SHOT-20261009.json`, `E:\b14-agnes30-RPM-ISOLATED-DIRECT-COMPARISON-20261009.json`. 키 및 모델 원문 응답은 저장하지 않음. **기존 B14 실패 판정은 유지하며, 새 호출은 종전 F4 시도 통계와 독립된 follow-up으로 기록.**

## 2026-10-09 짧은 일반 대화 A/B 추가 검증

견적 정보 추출과 독립적으로 정확히 동일한 일반 대화 입력 `안녕하세요. 한 문장으로 인사해 주세요.`를 Agnes 3.0 Flash에 적용했다.

| 구분 | B14 명시 선택 경유 | 로컬 Agnes 직접 API |
|---|---|---|
| 실제 모델 | `agnes-ai/agnes-3.0-flash` | `agnes-3.0-flash` |
| POST 수 | **1회** | **1회** |
| temperature / max_tokens | 0 / 100 | 0 / 100 |
| HTTP | **429** | **200** |
| 응답시간 | **1,328ms** | **2,922ms** |
| 대화 결과 | `upstream_rate_limited`, 답변 없음 | 응답 있음, 모델 ID 일치, 총 **94토큰** |
| 라우팅 제어 | `max_attempts=1`, `max_retries=0`, 외부 fallback 금지 | 직접 호출, 재시도 없음 |

**판정:** 한 문장 인사도 B14 경유에서는 429로 거부되는 반면 같은 입력·모델·temperature·token budget의 직접 API는 성공했다. 따라서 **견적 프롬프트의 복잡성이나 출력 길이는 이번 경로 차이를 설명하지 못한다.** 다만 B14에 저장된 Secret의 실제 계정/키 유형과 로컬 키가 동일한지는 검증되지 않았고, Agnes 제공자의 원본 오류 상세도 B14 응답에 보존되지 않아 **B14 코드 결함으로 확정하지 않는다**. 비밀값 조회·코드 변경·배포 없이 사용자 선택 모델 고정 조건으로 확인했다.

증거: `E:\b14-agnes30-SHORT-CHAT-ONESHOT-20261009.json`, `E:\b14-agnes30-SHORT-CHAT-DIRECT-ONESHOT-20261009.json`. 키·응답 원문은 저장소에 저장하지 않는다.

## Owner 결정 — 2026-10-09 평가 후순위 이동

운영 B14의 Agnes exact-model 경유 HTTP429가 짧은 대화·QKR 견적에서 반복됐고, 같은 모델의 로컬 직접 API/로컬 B14는 성공했다. 현재 고객 운영 가용성 미증명. **재시도 중단, 평가 대기열 마지막(9번), 상태 `ERROR_B14_HTTP429 / DEFERRED`.** 원인 분석은 [#3913](https://github.com/skerishKang/ai-revenue-lab/issues/3913) 및 Draft PR #3914에서 별도 계속한다. 수정 검증 전 `FINAL_PASS` 금지. 사용자가 명시하지 않은 모델 자동 대체·모델 삭제·운영 배포 금지.
