<!-- CURRENT_IMPLEMENTATION_NOTE_20261010 -->
> **이 문서의 10개 모델·`temperature=0.2`·`max_tokens<=4096` 등 아래 항목은 과거 평가 당시의 코드·실험 조건 감사**이며 현재 main의 동작 설명이 아닙니다. B14 native 옵션 소스 [PR #3984](https://github.com/skerishKang/ai-revenue-lab/pull/3984)가 이후 MERGED되어 Gateway/Platform의 누락 옵션 처리와 global 4096 처리 기준이 바뀌었습니다. B14 현재 정확한 등록 모델 수/제공자 ID는 **`apps/korean-ai-platform/app/pilot/b14_models.json`**을 직접 읽으세요(신규 등록 때마다 가변). [실행 계약](../../operations/B14_NATIVE_PROVIDER_PARAMETERS_2026-10-10.md); 미완료 B66→Core opt-in은 [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977) **LOCAL1**, B66 UI 후속은 [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906) **LOCAL2**. 옛 실측 점수/모델 수는 소급 수정하지 않습니다.
<!-- /CURRENT_IMPLEMENTATION_NOTE_20261010 -->

<!-- OWNER_MODEL_PRIORITY_20261010 -->
> **평가 순서 Owner 최신 결정(2026-10-10):** [현재 평가 우선순위](B14_OWNER_EVALUATION_PRIORITY_2026-10-10.md)에서 **Atria·Agnes는 가용성 문제가 있어 후순위, 개별 이슈는 보류 종료**했습니다. 아래 모델별 기존 재시험 필요성 분석은 기술적 판단으로만 보존하며, 두 모델을 우선 재호출하거나 정상 모델 개발을 지연시키지 않습니다. 이 결정으로 모델 등록·실행 API·수동선택·공식 파라미터 계약은 달라지지 않습니다.
<!-- /OWNER_MODEL_PRIORITY_20261010 -->

<!-- B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->
> **B14 역할 최신 원칙(2026-10-10):** [원제작사 모델·서빙 제공업체·변형 모델의 공식 사양 및 B14 실행 권한](../../architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)을 우선 확인합니다. **B14는 정확히 사용자가 선택한 모델을 해당 업체의 공식 API로 실행**하며, temperature/토큰/리즈닝을 임의 지정하거나 옵션을 조용히 바꾸지 않습니다. 원본 모델의 공식 사양과 실제 API 제공업체의 계약은 별도 증빙합니다. 과거 코드·평가 수치는 이 원칙의 구현 증명이 아닙니다.
<!-- /B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->

# B14 공식 모델 설정·기존 실측 재검증 감사 (2026-10-10)

**범위:** Owner가 유지하는 B14 등록 모델 10개와, 기존 문서에만 등장하는 비등록 무료 후보 3개. 본 문서는 **기존 실험 결과를 삭제하거나 새로운 실측으로 바꾸지 않는다.** B14 코드·키·배포·라우팅·B66 고객 구현은 변경하지 않는다.

**권한 기준:** `apps/korean-ai-platform/app/pilot/b14_models.json`은 모델·제공자 ID의 단일 소스이다. `groups.plus/pro/max`가 비어 있으며 사용자가 모델을 직접 선택한다. 제외된 모델의 부활, 자동 선택, 비용 경로 대체는 이 감사로 승인되지 않는다.

## 1. 확인된 공통 문제 (실행 코드 근거)

- `apps/korean-ai-platform/app/pilot/gateway.py`의 `_validate_body`: 명시한 `max_tokens`는 모든 모델에 **1..4096**; 생략 시 `None`. `temperature`를 생략하면 모든 모델에 **0.2**를 넣는다. `reasoning_effort`, `thinking`, `chat_template_kwargs`, `top_p`, `top_k` 등의 모델별 옵션은 현재 요청 경로에서 끝까지 전달되지 않는다.
- `apps/korean-ai-platform/app/pilot/platform.py`의 completed/streaming adapter: 모델·메시지와 `temperature` 및 `max_tokens`만 전달한다. 즉 공식 공급사 설정을 B14 운영 경로에서 재현했다고 볼 수 없다.
- `.github/scripts/b14_model_evaluation.py::request_body`: 역사적 공통값 `temperature=0, max_tokens=512`. 별도 한국어 견적 동일 조건 비교는 `temperature=0,max_tokens=3500`을 썼다. 이것은 **통제된 비교 조건**이지 공식 기본/권장 설정이 아니다.
- `docs/models/final-evaluation/B14_SAME_CASE_MODEL_COMPARISON_2026-10-09.md`의 V2 수치는 실제 해당 조건의 제한적 결과다. 현재 공식 설정 기준의 모델 우열로 재표시하지 않는다.
- 모델 컨텍스트 창, 모델 최대 출력량, 요청당 지정 출력 예산, 계정 TPM/RPM/RPD, reasoning 토큰은 서로 다른 개념. 최대 출력량을 무조건 `max_tokens`로 요청하지 않는다.

## 2. 현재 등록 10개: 재시험 판정

| B14 exact ID | 기존 실행 기록의 대표 조건 | 공식/실제 지원 대조 | 재시험 필요성 |
|---|---|---|---|
| `google/gemini-3.1-flash-lite` | `temperature=0, max_tokens=1800`; QKR-001..010 | Gemini 3.x 공식 기본 temperature **1.0 권고**; 추론 단계별 운영 전달 미검증 | **예 P1**: 공식 기본 + 지원 단계 |
| `google/gemini-3.5-flash-lite` | `temperature=0, max_tokens=1800/3500`; minimal/low/medium/high 별도 직결 측정 | 공식 기본 temperature 1.0 권고. 기존 저온 비교치는 별도 보존 | **예 P1**: 공식 기본 + 최소/중간 단계; 고강도는 출력 예산 확인 후 |
| `google/gemma-4-26b-a4b-it` | `temperature=0, max_tokens=1800`, minimal/high | Gemma 4 공식 `temperature=1.0, top_p=0.95, top_k=64`; high의 포맷·길이 실패는 능력 단정 금지 | **예 P1**: 권장 샘플링·출력 충분성·정확한 모델별 추론 |
| `google/gemma-4-31b-it` | 26B와 유사, 오류/형식 실패 존재 | 동일 Gemma 4 공식 샘플링 권장; 단일 1,800 예산으로 high 평가 곤란 | **예 P1**: 형식·끝맺음과 provider 오류 분리 |
| `sensenova/sensenova-6.8-flash-lite` | `temperature=0,max_tokens=1800/3500`; none/low/medium/high 측정 | 공식 일반 Thinking `1.0/0.95`, 일반 Instruct `0.7/0.8`; top_k·penalty 등도 모드별 권장 | **예 P1**: 모드별 공식 샘플링으로 QKR 재검증 |
| `poolside/laguna-s-2.1` | `temperature=0,max_tokens=1800`; thinking off/on 직결 실측 | 자체 공식 모델/엔드포인트의 기본값·지원 필드를 재확인. 원래 on/off 측정은 보존 | **예 P2**: 공급사 기본과 직결/B14 추론 전달 정합성 |
| `inception/mercury-2.5` | `temperature=0,max_tokens=1800/3500`; V2 9/10 strict | Mercury 2.5 전용 공식 sampling/effort 기본값은 추가 확인 필요; 과거 100토큰 length 재현 | **조건부 P2**: 공식 상세·API 호환 확인 후 출력/추론 차이만 재검증 |
| `atria/Atria-Dawn-Preview` | `temperature=0,max_tokens=1800/3500`; direct low/medium/high 일부 | 공식 reasoning effort 직접 호출 기록 있음. `none` HTTP422였으므로 지원값으로 주장 금지 | **조건부 P2**: 504/스트리밍 안정성 확보 후 공식 지원 수준 |
| `agnes-ai/agnes-3.0-flash` | `temperature=0,max_tokens=1800`; direct thinking off/on 일부 | `chat_template_kwargs.enable_thinking` 직결 실측은 보존. B14 HTTP429로 운영 미검증 | **보류**: 429 원인 해결 후 모드별 공식값/운영 전달 시험 |
| `experiential/qwen3.8-flash-next-uncensored` | 등록·스모크만 수행; 키 수정 뒤 HTTP429 | ExLab 중계 모델은 Qwen 원본 문서만으로 정확한 중계 API 세부 지원을 추정하지 않는다 | **보류**: 사용 가능해진 뒤 공급사 ID·허용 옵션 확인 후 QKR |

**판정 의미:** '예'는 기존 점수 소거·10×전수 즉시 재호출이 아니라 공식 설정 경로가 동작한 다음 **선정된 수준별** QKR-001..010을 재검증할 필요가 있다는 뜻이다. '보류'는 모델 능력 실패가 아닌 가용성/업스트림 승인 문제다.

## 3. 비등록 후보는 B14 등록 모델 수나 우열표에 섞지 않는다

- HCNSEC: 인증된 `GET /v1/models`에서 `longcat-2.5`, `Qwen3.8-Flash-Next` 확인. 별도 remote-preview 직결 최소 산술 Q&A는 **둘 다 HTTP200, 정답 2**(LongCat 6.165초, Qwen 4.391초). 이것은 QKR 견적 10건 성능이 아니다. LongCat 공식 `LongCat-2.5-Preview`와 HCNSEC `longcat-2.5`의 설정 전달 일치는 독립 확인한다. 아직 canonical B14 등록 대상 아님.
- Kilo `stepfun/step-5-preview-free`: 기록된 429는 가용성 실패로 분류; 정상 성능 점수로 변환 금지.
- Kilo `inclusionai/ling-3.1-flash`, `dots3-note:free`: 기존 `temperature=0,max_tokens=3500` 등 동일조건 실측만 보존; 공식 권장 파라미터 검증 전에는 공식 성능 평가로 표시 금지.
- 다른 문서/카탈로그의 발견 모델이 단일 소스에 등록됐다고 추정하지 않는다.

## 4. 공식 자료와 입증 수준

- [Google Gemini 3 가이드](https://ai.google.dev/gemini-api/docs/gemini-3): 기본 temperature=1.0 유지 권장. 모델별 실제 thinking 수준은 [공식 사고 설정](https://ai.google.dev/gemini-api/docs/thinking)에서 확인.
- [Google Gemma 4 모델 카드](https://ai.google.dev/gemma/docs/core/model_card_4): temperature=1.0, top_p=0.95, top_k=64. 모델 카드의 토큰/프롬프트 방식과 Google 중계 호환 API 옵션을 혼동하지 않는다.
- [SenseNova 6.8 공식 API](https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md): 모드별 sampling 매트릭스와 provider 예시.
- [LongCat 공식 API 문서](https://longcat.chat/platform/docs/OpenCode.html): `LongCat-2.5-Preview`의 `thinking` on/off. HCNSEC alias 전달 여부는 별도.
- 나머지 모델은 저장소의 개별 [F1..F6 평가 문서](.)에 기록한 출처와 upstream `/models`의 실제 필드를 재대조해야 하며, **확정되지 않은 기본값은 UNKNOWN**으로 기록한다.
- **검증 수준 표기:** 공식 문서 확인 / 제공사 인증 GET 확인 / 직접 공급사 POST 확인 / B14 운영 POST 확인 / B66 E2E 확인을 엄격하게 분리한다.

## 5. 필요한 후속 실행 순서 (이 문서는 실행·배포 승인 자체가 아님)

1. **P0 B14 계약/어댑터 정합성:** 정확한 model/provider ID별 허용/권장 샘플링, reasoning 옵션, 기본 생략 처리, 출력 토큰 상한을 표준 프로필로 관리. '공급사 기본값 사용'은 해당 키를 **전송하지 않는 것**, `temperature=0.2`로 변환하는 것이 아니다. canonical B14 모델 등록 JSON의 신원 권한을 유지; 프로필 추가는 스키마/검증/문서/회귀 테스트 후 별도 PR. 명시적 사용자 모델 선택 유지; 자동 라우팅/기본 모델/유료대체 변경 불가.
2. **P0 파라미터 전달 단위검증:** 각 provider의 실제 HTTP JSON shape를 fixture로 기록. unsupported 옵션은 사전에 오류로 구분하고 임의 매핑하지 않음; stream/non-stream parity, explicit/omitted distinction, max_tokens vs max_completion_tokens, timeout, 429/504 분류와 secret 안전성 검사.
3. **P1 효율적 재검증:** QKR-001..010 **공식 설정 프로필** 먼저 (Gemini 3.1/3.5, Gemma 4 26B/31B, SenseNova), 이미 신뢰되는 동일조건 이력은 병기. reasoning 비교는 provider가 지원·중계하는 수준만. 고강도는 소규모 예비 QKR + length 검증 후 확대. 도중 공급사 429·504면 멈추고 availability 실패로 분리.
4. **P2 지연/조건부:** Poolside/Mercury/Atria 지원 옵션 재확인 및 필요한 범위만 시험; Agnes·ExLab 제공사 정상화 전에는 불필요한 반복 금지; HCNSEC는 별도 직결 공식 모드 QKR 후 Owner가 등록 결정.
5. **완료 기준:** provider 공식 URL/확인일, exact endpoint/model, 원 요청 파라미터의 안전한 요약/해시, `finish_reason`, provider/model 응답 식별, 사용 토큰·추론 토큰, 유효 답변, HTTP 상태, 중앙 B14/B66 경유 여부, QKR strict 점수/가용성을 모두 분리해서 저장. 이전과 새 점수는 **다른 실험군**으로 표기한다.

## 6. 관련 문서/이슈 교차 참조

- **신규 구현 이슈 [#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977)**: 모델별 API 파라미터 전달/기본값 보존/회귀검증. 기존 운영·실측·UX의 이슈를 대체하지 않는다.
- 기존 이슈 [#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554)(운영 모델 실행), [#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676)(비교 평가 harness/공식설정 재측정), [#3906](https://github.com/skerishKang/ai-revenue-lab/issues/3906)(추론 UX Owner 제안), [#3913](https://github.com/skerishKang/ai-revenue-lab/issues/3913)(Agnes 429), [#3922](https://github.com/skerishKang/ai-revenue-lab/issues/3922)(Atria 504), #3790(사용자 선택 UI), #3789(제외 모델 가드).
- 역사적 실측: `B14_FINAL_MODEL_EVALUATION_2026-10-09.md`, `B14_SAME_CASE_MODEL_COMPARISON_2026-10-09.md`, 개별 모델별 `B14_FINAL_*.md`. 기록을 소급 수정·성공으로 둔갑시키지 않는다.
- 평가 규약: `docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md`.
