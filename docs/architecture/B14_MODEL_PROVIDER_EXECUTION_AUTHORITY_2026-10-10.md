# B14 역할 및 원제작사·제공업체 모델 사양의 권한 경계

```text
DOC_STATUS = CANONICAL_B14_EXECUTION_ROLE
OWNER = PADIEM Product Owner
DATE = 2026-10-10
SCOPE = B14 model/provider identity, model-native request fidelity, provenance, routing/execution
SOURCE_OF_REGISTERED_IDENTITIES = apps/korean-ai-platform/app/pilot/b14_models.json
```

## 1. 한 문장 정의

**B14는 사용자가 선택한 정확한 모델을 실제 제공업체의 공식 API 규약에 맞춰 실행하는 Provider/Model 연결·실행 계층이다. 모델의 추론 방식·샘플링·출력 예산을 임의로 최적화하거나 다른 모델을 대신 선택하는 계층이 아니다.**

'Router Platform'이라는 장기 기술적 명칭은 유지하지만, **현재 Owner가 승인한 Padiem 고객 경로는 사용자 명시 선택(Exact Model ID)만 실행**한다. 과거 generic `b14/auto` 구현이나 향후 최적화 구상은 현재 사용자의 암묵적 모델 선택·자동 fallback 권한이 아니다.

## 2. 모델의 두 가지 출처와 별도 제공업체

| 유형 | 모델 정체성 | 권위 있는 출처 |
|---|---|---|
| **A. 원제작사 모델을 변경 없이 제공** | 원제작사가 개발한 원본 모델을 그 회사가 직접 제공하거나 타 API 업체가 **변경 없이 중계** | 모델 자체의 기본 기능·권장 추론/샘플링은 **원제작사 모델별 공식 문서**. 실제 HTTP 엔드포인트·파라미터 이름·인증·허용값·제한은 **현재 호출하는 API 제공업체의 공식 문서 및 인증된 응답** |
| **B. 제공업체가 개발·수정·튜닝한 별도 모델** | 제공업체 고유 모델, 파생/미세조정/uncensored/커스텀 서빙 변형 등 **문서로 확인된 별도 모델** | 해당 업체가 그 **정확한 서비스 모델 ID**에 대해 발표한 공식 문서가 우선. 원본 모델 카드의 동일 설정을 상속한다는 **업체의 명시적 근거가 없으면 추정 금지** |

- **모델 제작사**(`model_developer`), **기반 모델**(`base_model`), **변형 관계**(`variant_kind`), **API 제공업체**(`serving_provider`), **B14 공개 ID**(`b14_id`), **업체 upstream ID**(`upstream_model`)는 다른 개념이다.
- 한 업체가 API 별칭(alias)을 붙였다는 이유만으로 별도 튜닝 모델로 간주하지 않는다. 반대로 모델 이름이 유사하다는 이유만으로 원본과 완전히 동일하다고 간주하지 않는다.
- **증거가 없으면 `PROVENANCE_UNVERIFIED` / `PARAMETER_SUPPORT_UNKNOWN`**으로 표시하고 추론 능력·기본값을 만들어 내지 않는다. 제공업체의 지원 파라미터를 원제작사 모델 카드만 보고 자동 허용하지 않는다.
- 예: HCNSEC `Qwen3.8-Flash-Next`와 ExLab `qwen3.8-flash-next-uncensored`는 서로 다른 **실제 제공업체 + upstream ID**이다. 둘을 하나의 'Qwen3.8 프로필'로 묶지 않는다. HCNSEC `longcat-2.5`와 LongCat 원제작사 표기 모델의 기능·옵션이 동일한지도 업체 자료로 확인한다.

## 3. 사양의 출처 우선순위와 요청 처리

1. Owner가 허가하고 사용자가 고른 **B14 exact ID**를 현재 중앙 등록소에서 조회한다. 제공업체/실제 모델이 모호하거나 등록되지 않았거나 제외된 경우 실행 전 실패한다.
2. 선택된 서비스 모델이 A/B 중 어떤 유형인지 **공식 자료로 확인**한다. 확인되지 않은 변형 여부를 추정하지 않는다.
3. 원제작사 **모델 고유 사양**(추론 수준/기본 샘플링/기능/출력 한도)과 제공업체 **실제 API 계약**(모델 ID, 요청 필드, 허용값, 최대치/서빙 제약, 응답 필드)을 분리 기록한다.
4. **사용자가 값을 지정하지 않은 추론·샘플링 파라미터는 HTTP 요청에서 생략**한다. B14가 `temperature=0.2` 같은 범용 모델값으로 대체하지 않는다. 제공업체가 문서로 요구하는 **필수 필드**는 그 계약대로 처리하고 근거를 남긴다.
5. 사용자가 지원하는 설정을 명시했을 때만 **해당 API의 공식 필드/단위**로 변환한다. `reasoning_effort`, `thinking`, `chat_template_kwargs.enable_thinking` 등이 모든 업체에서 교환 가능하다고 가정하지 않는다. 공식적으로 지원하지 않는 값은 **명시적 오류**를 반환하며, 조용히 삭제·무시·다른 수준으로 바꾸지 않는다.
6. **max context**, **model maximum output**, **request output budget**, **계정 RPM/TPM**, **서비스 측 운영 안전 제한**을 별도로 기록한다. 최대 출력량을 항상 요청값으로 넣지 않고, 고정 4096 같은 B14 제품 제한을 업체 모델의 최대 출력량으로 표기하지 않는다. 서비스 보호용 별도 상한이 필요하다면 모델 사양이 아닌 **B14 운영 한도**로 명시하고 사용자 요청을 몰래 자르지 않는다.
7. 응답에서 실제 `model`, 완료 사유(`finish_reason`), HTTP 상태/시간, usage/추론 토큰(존재 시)과 출력 여부를 검증한다. API 등록/키 존재/HTTP200/실제 모델 출력/고객 업무 성공은 **서로 다른 검증 단계**이다.

```text
REQUEST_OMITTED_OPTION = OMIT_FROM_UPSTREAM (unless official serving API requires it)
MODEL_SAMPLING_DEFAULT_OWNER = ACTUAL_PROVIDER_OR_MODEL
B14_ARBITRARY_TEMPERATURE_OR_THINKING = FORBIDDEN
B14_UNDOCUMENTED_TOKEN_CAP_AS_MODEL_LIMIT = FORBIDDEN
UNKNOWN_API_PARAMETER = EXPLICIT_UNSUPPORTED (not silently rewritten)
```

## 4. B14가 담당하는 것과 담당하지 않는 것

| B14 담당 | B14 담당 아님 |
|---|---|
| Owner 승인된 provider + exact 모델 ID 등록·실행 가능 여부·금지 모델 검증 | 사용자 대신 모델을 선택하거나 기본 모델을 임의 지정 |
| 제공업체 API origin/호스트/인증 바인딩, 자격증명 격리, 전송·응답·오류 규격 | 모델 고유 temperature/reasoning/기본 출력량을 B14 취향대로 설정 |
| 제조사 모델 원본과 제공업체 변형 모델의 **근거 있는 구분 및 사양 출처 기록** | 출처가 확인되지 않은 모델의 원본 사양 복사 |
| 업체별 공식 옵션의 정확한 요청 변환, 스트리밍/일반 호출·이미지 등 지원 기능별 검증 | 근거 없는 추론 단계 호환 가정 또는 unsupported 옵션 침묵 제거 |
| 서빙 준비 상태, 실제 모델 정체성, 품질/가용성 관찰, 네트워크·보안 운영 경계 | B66 QuoteCore 금액 계산, PDF 양식 구현, B62·Claw의 UX·기억·업무 판단, Control Plane 요금제/신원 권한 |

**B14가 하지 말아야 할 '임의 조정'**은 **모델 출력 생성의 의미를 바꾸는 숨은 파라미터 보정**을 말한다. TLS/인증/타임아웃/유효성 검사/비밀 보호/실패 처리 등 **서비스 운영 안전 장치**는 그대로 필요하다. 사용자가 고른 모델에 실패가 발생했다고 해서 다른 업체·모델로 이동하지 않는다.

## 5. 원본 문서·중계업체 문서의 충돌 처리

- 업체가 원본 모델의 옵션을 지원하지 않으면, **원본 모델 권장값을 B14에서 강제로 전송하지 않는다.** 이 서빙 경로에서 해당 옵션은 지원되지 않는다고 표시한다.
- 업체가 원본과 다른 기본값을 명시한 경우에는 **실제 업체의 서빙 기본값과 모델 원본 권장값을 나란히 기재**한다. 이를 동일한 모델 설정으로 허위 표기하지 않는다.
- 업체가 별도 튜닝/변형 모델을 공표한 경우에는 **업체 공식 변형 모델 문서**가 우선이며 원제작사 문서를 무조건 상속하지 않는다.
- 업체가 API 모델 목록만 노출하고 정확한 문서가 없다면 **실측으로 확인된 HTTP/파라미터 지원은 '공식 문서 확인'이 아니라 '제공업체 실제 API 관찰'**로 기재한다. 원본/변형 여부는 UNKNOWN으로 유지한다.

## 6. 실행 계층 간 경계 (현재 계약)

```text
Customer selects exact model (+ supported optional setting)
    -> Product UI (B62/B66/Claw) / IP-CORE and IP-ENGINE where applicable
    -> B14 current exact registry + Owner exclusion + credential readiness
    -> model provenance + exact serving-provider API contract
    -> original provider-specific request (no invented sampling/effort)
    -> chosen provider/model only; truthful response/evidence/error
```

- **B14:** 실제 provider/model 호출·공식 모델 옵션 지원·실행 증거.
- **B62/B66/Claw:** 사용자 인터페이스, 업무·대화 입력, *지원되는 옵션* 선택 표시; 실제 provider 자격증명/모델 사양의 독자 재정의 금지.
- **IP-CORE/ENGINE:** 범용 작업·에이전트 의미와 서비스 연결; 모델의 별도 출처나 임의 추론 파라미터를 생성하는 두 번째 라우터 금지.
- **IP-CONTROL:** 신원·권한·요금제·사용량 정책; 모델 자체 공식 기본값의 소유자 아님.
- **#3906:** 2026-10-10 현재 Owner가 B66의 추론 수준 UI 구현을 승인하여 LOCAL1에 배정했음. **승인된 것은 UX 소스 작업**이지 공식 옵션 검증 생략이나 Production 자동 활성화가 아니다. B14 서버의 실제 파라미터 지원은 **#3977**이 선행 기준.
- **#2698:** 장기 자동 라우터 구상은 별도 보류 이슈. 현 고객 경로에 자동 모델 선택/무단 fallback을 켜는 허가가 아니다.

## 7. 구현 현황, 발견된 위반 및 이관

2026-10-10 확인한 `origin/main`에서 다음은 **아직 수정되지 않은 코드 사실**이다.
- `app/pilot/gateway.py`, `schemas.py`, `platform.py`: 미지정 temperature를 `0.2`로 대체하고 일반 요청 `max_tokens` 명시값을 4096 이하로 제한.
- `static/start.js`, `static/workspace.js`, `app/pilot/ui.py`: 일반 사용자 요청에 `temperature=0.2`, 출력 512/300 등 고정값을 넣음. Atria 특별값 `temperature=0,max_tokens=1800`도 있음.
- B14 generic adapter는 모델별 공식 reasoning/sampling 옵션을 그대로 전달하지 못함.
- `b14_models.json`은 provider ID/origin + B14 exact ID/upstream ID를 구분하지만 **원제작사/제공업체 변형 관계의 공식 증빙·프로필 스키마는 아직 없음**.

코드 변경·테스트·출처 매핑 구현은 **[#3977](https://github.com/skerishKang/ai-revenue-lab/issues/3977)**에서 관리한다. 정확도 재측정은 **[#2676](https://github.com/skerishKang/ai-revenue-lab/issues/2676)**, 업무 실제 실행은 **[#3554](https://github.com/skerishKang/ai-revenue-lab/issues/3554)**, 관리자 UI는 **[#2107](https://github.com/skerishKang/ai-revenue-lab/issues/2107)**. 임의 기본값을 없애는 코드/배포를 이 문서 수정 완료와 혼동하지 않는다.

## 8. 출처 기록·검증 완료 조건

각 서비스 모델·서빙 경로마다 최소 다음을 기록한다.

```text
B14_ID; SERVING_PROVIDER_ID; SERVING_API_ORIGIN; UPSTREAM_MODEL_ID
MODEL_DEVELOPER; BASE_MODEL_ID_OR_UNKNOWN; VARIANT_CLASS_AND_EVIDENCE_OR_UNKNOWN
MANUFACTURER_OFFICIAL_DOC_URL_AND_CHECKED_AT_OR_UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL_AND_CHECKED_AT_OR_UNKNOWN
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE_OR_NOT_TESTED
SUPPORTED_SAMPLE_PARAMS; SUPPORTED_REASONING_PARAMS; RECOMMENDED_OR_NATIVE_DEFAULTS
MAX_INPUT_CONTEXT; MODEL_MAX_OUTPUT; SERVING_MAX_OUTPUT; REQUEST_BUDGET_CONTRACT
PARAMETER_PASSTHROUGH_TEST; LIVE_RESPONSE_IDENTITY; STREAM_NONSTREAM_PARITY
```

금액/실측점수 등은 출처·날짜·실험 조건을 분리한다. 모델 설명·제공업체 문서·실제 API 결과가 다른 경우 **불일치를 드러내고 UNKNOWN을 유지**한다. GitHub 문서에 API 키/원본 고객 데이터는 남기지 않는다.

## 9. 우선하는 관련 문서

- [B14 모델 등록 단일 소스](../operations/B14_MODEL_REGISTRY_SINGLE_SOURCE.md)
- [Owner 모델 선택/변경 권한](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)
- [B14 모델 공식 파라미터·과거 평가 감사](../models/final-evaluation/B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md)
- [전체 계층 역할](PADIEM_AI_VERTICAL_STACK.md), [Capability Ownership](PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md)
- [B14 제품 charter](../../apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md)

**우선순위:** Owner 최신 명시 결정 > 현재 등록/실행 권한(코드) > 공식 모델/서빙 API 근거 > 최신 B14 역할·운영 문서 > 과거 시험·제안. 단, 현재 코드가 이 문서와 다르면 **코드의 실제 동작이 이상한 것이므로 미해결 구현 작업으로 기록**하며 문서가 소스 변경을 대신하지 않는다.
