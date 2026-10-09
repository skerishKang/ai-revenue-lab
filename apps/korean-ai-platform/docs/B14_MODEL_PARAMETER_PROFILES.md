# B14 등록 모델별 공식 파라미터 프로필 (#3977)

> 이 문서는 `apps/korean-ai-platform/app/pilot/model_parameter_profiles.py` 에서 생성됩니다. 직접 편집하지 말고 소스를 수정한 뒤 재생성하십시오.

```text
PROFILE_SCHEMA_VERSION=1
B14_OPERATIONAL_REQUEST_TOKEN_CEILING=4096
TRANSPORT_BASELINE=temperature,max_tokens
CANONICAL_OPTIONAL_FIELDS=top_p,top_k,reasoning_effort,thinking
UNSPECIFIED_PARAMETERS=OMITTED
UNKNOWN_CAPABILITY=FAIL_CLOSED
PASSTHROUGH_TEST=NOT_TESTED
```

`temperature`와 `max_tokens`는 등록된 모든 OpenAI 호환 엔드포인트가 광고하는 전송 기본 필드다. 사용자가 지정하지 않으면 전송하지 않는다. 그 외 옵션은 아래 표에서 해당 exact 모델이 문서로 지원한다고 표기된 경우에만 전달된다.

## 요약

| B14 exact ID | serving provider | upstream model | variant | 지원 옵션 | 근거 수준 | passthrough |
|---|---|---|---|---|---|---|
| `agnes-ai/agnes-3.0-flash` | `agnes-ai` | `agnes-3.0-flash` | `unknown` | thinking | `provider_direct_post` | `NOT_TESTED` |
| `atria/Atria-Dawn-Preview` | `atria` | `Atria-Dawn-Preview` | `manufacturer_unmodified` | reasoning_effort | `provider_direct_post` | `NOT_TESTED` |
| `experiential/qwen3.8-flash-next-uncensored` | `experiential` | `qwen3.8-flash-next-uncensored` | `provider_variant` | — | `unverified` | `NOT_TESTED` |
| `google/gemini-3.1-flash-lite` | `google` | `gemini-3.1-flash-lite` | `manufacturer_unmodified` | top_p, reasoning_effort | `official_doc` | `NOT_TESTED` |
| `google/gemini-3.5-flash-lite` | `google` | `gemini-3.5-flash-lite` | `manufacturer_unmodified` | top_p, reasoning_effort | `official_doc` | `NOT_TESTED` |
| `google/gemma-4-26b-a4b-it` | `google` | `gemma-4-26b-a4b-it` | `manufacturer_unmodified` | top_p, top_k | `official_doc` | `NOT_TESTED` |
| `google/gemma-4-31b-it` | `google` | `gemma-4-31b-it` | `manufacturer_unmodified` | top_p, top_k | `official_doc` | `NOT_TESTED` |
| `inception/mercury-2.5` | `inception` | `mercury-2.5` | `manufacturer_unmodified` | — | `unverified` | `NOT_TESTED` |
| `poolside/laguna-s-2.1` | `poolside` | `poolside/laguna-s-2.1` | `manufacturer_unmodified` | thinking | `provider_direct_post` | `NOT_TESTED` |
| `sensenova/sensenova-6.8-flash-lite` | `sensenova` | `sensenova-6.8-flash-lite` | `manufacturer_unmodified` | — | `unverified` | `NOT_TESTED` |

## 모델별 상세

### `agnes-ai/agnes-3.0-flash`

```text
SERVING_PROVIDER_ID=agnes-ai
SERVING_API_ORIGIN=https://apihub.agnes-ai.com/v1
UPSTREAM_MODEL_ID=agnes-3.0-flash
MODEL_DEVELOPER=UNKNOWN
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=unknown
VARIANT_EVIDENCE=Agnes publishes the model but its upstream base/variant relationship is not documented; provenance stays UNKNOWN.
MANUFACTURER_OFFICIAL_DOC_URL=UNKNOWN
MANUFACTURER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=UNKNOWN
PROVIDER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=thinking
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=UNKNOWN
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=provider_direct_post
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `thinking` | `chat_template_kwargs.enable_thinking` | `boolean` | — | Agnes direct chat_template_kwargs.enable_thinking observation (#3906). |

### `atria/Atria-Dawn-Preview`

```text
SERVING_PROVIDER_ID=atria
SERVING_API_ORIGIN=https://api.atria-asi.ai/v1
UPSTREAM_MODEL_ID=Atria-Dawn-Preview
MODEL_DEVELOPER=Atria
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Atria preview model served by Atria's own API.
MANUFACTURER_OFFICIAL_DOC_URL=UNKNOWN
MANUFACTURER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=UNKNOWN
PROVIDER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=reasoning_effort
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=UNKNOWN
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=provider_direct_post
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `reasoning_effort` | `reasoning_effort` | `enum` | low, medium, high | Atria direct reasoning_effort observation; 'none' returned HTTP 422 (#3906). |

### `experiential/qwen3.8-flash-next-uncensored`

```text
SERVING_PROVIDER_ID=experiential
SERVING_API_ORIGIN=https://api.experientiallabs.ai/v1
UPSTREAM_MODEL_ID=qwen3.8-flash-next-uncensored
MODEL_DEVELOPER=Qwen (Alibaba) base, modified by Experiential Labs
BASE_MODEL_ID=qwen3.8-flash-next
VARIANT_CLASS=provider_variant
VARIANT_EVIDENCE=Model id declares an 'uncensored' derivative; Experiential Labs documents this exact served model (GET /api/models/qwen3.8-flash-next-uncensored).
MANUFACTURER_OFFICIAL_DOC_URL=UNKNOWN
MANUFACTURER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://api.experientiallabs.ai/v1
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_public_model_detail_2026-10-10
SUPPORTED_OPTIONAL_PARAMS=UNKNOWN
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=262144
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=unverified
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

문서로 확인된 추가 옵션이 없다(`PARAMETER_SUPPORT_UNKNOWN`). 명시적 추가 옵션 요청은 422로 거부된다.

### `google/gemini-3.1-flash-lite`

```text
SERVING_PROVIDER_ID=google
SERVING_API_ORIGIN=https://generativelanguage.googleapis.com/v1beta/openai
UPSTREAM_MODEL_ID=gemini-3.1-flash-lite
MODEL_DEVELOPER=Google
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Gemini model served by Google's own API.
MANUFACTURER_OFFICIAL_DOC_URL=https://ai.google.dev/gemini-api/docs/gemini-3
MANUFACTURER_DOC_CHECKED_AT=2026-10-10
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://ai.google.dev/gemini-api/docs/thinking
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=top_p,reasoning_effort
RECOMMENDED_OR_NATIVE_DEFAULTS=temperature=1.0
MAX_INPUT_CONTEXT=1048576
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=official_doc
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `top_p` | `top_p` | `number` | 0.0..1.0 | Google Gemini OpenAI-compatible sampling surface (top_p). |
| `reasoning_effort` | `reasoning_effort` | `enum` | minimal, low, medium, high | Google Gemini thinking settings via OpenAI-compatible reasoning_effort (#3906). |

### `google/gemini-3.5-flash-lite`

```text
SERVING_PROVIDER_ID=google
SERVING_API_ORIGIN=https://generativelanguage.googleapis.com/v1beta/openai
UPSTREAM_MODEL_ID=gemini-3.5-flash-lite
MODEL_DEVELOPER=Google
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Gemini model served by Google's own API.
MANUFACTURER_OFFICIAL_DOC_URL=https://ai.google.dev/gemini-api/docs/gemini-3
MANUFACTURER_DOC_CHECKED_AT=2026-10-10
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://ai.google.dev/gemini-api/docs/thinking
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=top_p,reasoning_effort
RECOMMENDED_OR_NATIVE_DEFAULTS=temperature=1.0
MAX_INPUT_CONTEXT=1048576
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=official_doc
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `top_p` | `top_p` | `number` | 0.0..1.0 | Google Gemini OpenAI-compatible sampling surface (top_p). |
| `reasoning_effort` | `reasoning_effort` | `enum` | minimal, low, medium, high | Google Gemini thinking settings via OpenAI-compatible reasoning_effort (#3906). |

### `google/gemma-4-26b-a4b-it`

```text
SERVING_PROVIDER_ID=google
SERVING_API_ORIGIN=https://generativelanguage.googleapis.com/v1beta/openai
UPSTREAM_MODEL_ID=gemma-4-26b-a4b-it
MODEL_DEVELOPER=Google
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Gemma model served by Google's own API.
MANUFACTURER_OFFICIAL_DOC_URL=https://ai.google.dev/gemma/docs/core/model_card_4
MANUFACTURER_DOC_CHECKED_AT=2026-10-10
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://ai.google.dev/gemma/docs/core/model_card_4
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=top_p,top_k
RECOMMENDED_OR_NATIVE_DEFAULTS=temperature=1.0,top_p=0.95,top_k=64
MAX_INPUT_CONTEXT=262144
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=official_doc
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `top_p` | `top_p` | `number` | 0.0..1.0 | Gemma 4 official model card recommended sampling (top_p=0.95). |
| `top_k` | `top_k` | `integer` | 1..None | Gemma 4 official model card recommended sampling (top_k=64). |

### `google/gemma-4-31b-it`

```text
SERVING_PROVIDER_ID=google
SERVING_API_ORIGIN=https://generativelanguage.googleapis.com/v1beta/openai
UPSTREAM_MODEL_ID=gemma-4-31b-it
MODEL_DEVELOPER=Google
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Gemma model served by Google's own API.
MANUFACTURER_OFFICIAL_DOC_URL=https://ai.google.dev/gemma/docs/core/model_card_4
MANUFACTURER_DOC_CHECKED_AT=2026-10-10
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://ai.google.dev/gemma/docs/core/model_card_4
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=top_p,top_k
RECOMMENDED_OR_NATIVE_DEFAULTS=temperature=1.0,top_p=0.95,top_k=64
MAX_INPUT_CONTEXT=262144
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=official_doc
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `top_p` | `top_p` | `number` | 0.0..1.0 | Gemma 4 official model card recommended sampling (top_p=0.95). |
| `top_k` | `top_k` | `integer` | 1..None | Gemma 4 official model card recommended sampling (top_k=64). |

### `inception/mercury-2.5`

```text
SERVING_PROVIDER_ID=inception
SERVING_API_ORIGIN=https://api.inceptionlabs.ai/v1
UPSTREAM_MODEL_ID=mercury-2.5
MODEL_DEVELOPER=Inception Labs
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Mercury model served by Inception's own API.
MANUFACTURER_OFFICIAL_DOC_URL=UNKNOWN
MANUFACTURER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=UNKNOWN
PROVIDER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=UNKNOWN
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=UNKNOWN
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=unverified
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

문서로 확인된 추가 옵션이 없다(`PARAMETER_SUPPORT_UNKNOWN`). 명시적 추가 옵션 요청은 422로 거부된다.

### `poolside/laguna-s-2.1`

```text
SERVING_PROVIDER_ID=poolside
SERVING_API_ORIGIN=https://inference.poolside.ai/v1
UPSTREAM_MODEL_ID=poolside/laguna-s-2.1
MODEL_DEVELOPER=Poolside
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted Poolside model served by Poolside's own API.
MANUFACTURER_OFFICIAL_DOC_URL=UNKNOWN
MANUFACTURER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=UNKNOWN
PROVIDER_DOC_CHECKED_AT=UNKNOWN
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=thinking
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=1000000
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=provider_direct_post
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |
|---|---|---|---|---|
| `thinking` | `chat_template_kwargs.enable_thinking` | `boolean` | — | Poolside standard request maps thinking to chat_template_kwargs.enable_thinking (#3906). |

### `sensenova/sensenova-6.8-flash-lite`

```text
SERVING_PROVIDER_ID=sensenova
SERVING_API_ORIGIN=https://token.sensenova.ai/v1
UPSTREAM_MODEL_ID=sensenova-6.8-flash-lite
MODEL_DEVELOPER=SenseNova
BASE_MODEL_ID=UNKNOWN
VARIANT_CLASS=manufacturer_unmodified
VARIANT_EVIDENCE=Manufacturer-hosted SenseNova model served by SenseNova's own API.
MANUFACTURER_OFFICIAL_DOC_URL=https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md
MANUFACTURER_DOC_CHECKED_AT=2026-10-10
PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL=https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md
PROVIDER_DOC_CHECKED_AT=2026-10-10
PROVIDER_AUTHENTICATED_MODELS_EVIDENCE=provider_authenticated_models_not_retested
SUPPORTED_OPTIONAL_PARAMS=UNKNOWN
RECOMMENDED_OR_NATIVE_DEFAULTS=UNKNOWN
MAX_INPUT_CONTEXT=256000
MODEL_MAX_OUTPUT=UNKNOWN
SERVING_MAX_OUTPUT=UNKNOWN
REQUEST_BUDGET_CONTRACT=explicit_only_bounded_by_b14_service_ceiling
EVIDENCE_LEVEL=unverified
PARAMETER_PASSTHROUGH_TEST=NOT_TESTED
STREAM_NONSTREAM_PARITY=NOT_TESTED
```

문서로 확인된 추가 옵션이 없다(`PARAMETER_SUPPORT_UNKNOWN`). 명시적 추가 옵션 요청은 422로 거부된다.
