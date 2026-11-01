# BYOK 공급사별 최대 출력 토큰(max output tokens) 공식 문서 조사

- **조사일(확인일): 2026-11-02** — 아래 모든 URL/수치는 이 날짜에 공식 문서에서 직접 확인함.
- **배경**: ai-revenue-lab BYOK 커스텀 모델 직결 경로. 현재 코드는 Anthropic 직결 요청에 `max_tokens=4096` 고정, OpenAI 호환/Google 와이어에는 `max_tokens` 미전송(공급자 기본값 적용). 본 문서는 그 동작의 근거가 되는 공급사별 공시 수치를 모은 것.
- **원칙**: 문서에 수치가 없으면 **"확인 못 함"** 으로 기재(추측으로 채우지 않음). 인용은 문서 원문(영문) 그대로.

---

## 결론 요약 (1,000자 내)

9개 공급사 중 6곳에서 문서상 수치를 확정했다(모두 2026-11-02 확인). Anthropic은 현행 비교표 기준 claude-sonnet-4-5·claude-haiku-4-5 "64K tokens", claude-opus-4-1 "32K tokens". Google Gemini는 gemini-2.5-flash·flash-lite·pro 모두 개별 모델 페이지에서 "Output token limit 65,536"(컨텍스트 1,048,576). Groq llama-3.1-8b-instant는 모델 목록표에 "MAX COMPLETION TOKENS 131,072". DeepSeek 현행 모델은 max_tokens가 "between 1 and 384K (393216)", 미설정 시 "default is 8K in non-thinking mode, 64K in thinking mode (128K with reasoning_effort set to max)". xAI는 chat completions의 `max_output_tokens`가 "Defaults to 128,000 when unset". OpenRouter는 미지정 파라미터를 상류로 그대로 전달해 공급자 기본값을 적용한다고 문서에 명시하며, 모델별 상한은 GET /api/v1/models의 `top_provider.max_completion_tokens`로 확인한다(실측: deepseek/deepseek-chat 16,000). **확인 못 함**: Anthropic 레거시 8종(3.5/3.7/3/4.0/opus-4-5 등)은 현행 비교표에서 삭제돼 수치 부재. OpenAI는 생략 시 적용되는 기본 출력 상한 수치를 공식 스펙에 공시하지 않음. Gemini `maxOutputTokens` 생략 시 기본값 문구는 현행 레퍼런스에서 확인 불가(모델별 상한 조회용 `outputTokenLimit` 필드만 문서화). DeepSeek deepseek-chat은 현행 문서에서 모델 자체가 제외(2024-07 과거 문서: 기본 4096, 베타 최대 8192). xAI grok-4-1-fast-non-reasoning은 모델별 출력 한도 미게재. Perplexity sonar는 Chat Completions 지원 종료(2026-09-27)로 수치 부재(sonar-pro만 "8k" 명시). HuggingFace 라우터는 출력 토큰 한도 문서가 없다(컨텍스트 길이만 제공).

---

## 표: 공급사별 확인 결과

| # | 공급사 | 모델 / 항목 | 문서 수치 (원문 인용) | 공식 문서 URL | 확인일 |
|---|--------|------------|----------------------|---------------|--------|
| 1 | Anthropic | claude-sonnet-4-5 | "Max output: **64K tokens**" | <https://docs.claude.com/en/docs/about-claude/models/overview> | 2026-11-02 |
| 2 | Anthropic | claude-haiku-4-5 | "**64K tokens**" | (상동) | 2026-11-02 |
| 3 | Anthropic | claude-opus-4-1 | "**32K tokens**" | (상동) | 2026-11-02 |
| 4 | Anthropic | claude-3-5-sonnet, claude-3-5-haiku, claude-3-7-sonnet, claude-sonnet-4, claude-opus-4, claude-opus-4-5, claude-3-opus, claude-3-haiku | **확인 못 함** — 현행 모델 비교표에 미수록 [1] | (비교표: 상동 overview URL) | 2026-11-02 |
| 5 | OpenAI | chat completions에서 `max_tokens` 생략 시 출력 상한 | **확인 못 함(기본 수치 공시 없음)** — 스펙상 optional / nullable, 기본값 문구 없음 [2] | <https://github.com/openai/openai-openapi/blob/master/openapi.yaml> (ChatCompletionCreateParams) | 2026-11-02 |
| 6 | Google Gemini | gemini-2.5-flash | "Output token limit **65,536**" (컨텍스트 1,048,576) | <https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash> | 2026-11-02 |
| 7 | Google Gemini | gemini-2.5-flash-lite | "Output token limit **65,536**" (1,048,576) | <https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite> | 2026-11-02 |
| 8 | Google Gemini | gemini-2.5-pro | "Output token limit **65,536**" (1,048,576) | <https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro> | 2026-11-02 |
| 9 | Google Gemini | `generateContent` `maxOutputTokens` 생략 시 기본값 | **확인 못 함** — 현행 레퍼런스에 기본값 문구 없음 [3] | <https://ai.google.dev/api/generate-content> | 2026-11-02 |
| 10 | DeepSeek | deepseek-chat | **확인 못 함** — 현행 문서 모델 목록에서 제외 [4] | <https://api-docs.deepseek.com/api/create-chat-completion> | 2026-11-02 |
| 11 | DeepSeek | (현행 모델 공통) `max_tokens` 범위·기본값 | "The value must be between **1 and 384K (393216)**. When not set, the default is **8K in non-thinking mode, 64K in thinking mode (128K with reasoning_effort set to max)**." | <https://api-docs.deepseek.com/api/create-chat-completion> | 2026-11-02 |
| 12 | DeepSeek | DeepSeek-V4-Pro-0813 (참고) | "CONTEXT LENGTH 1M / MAX OUTPUT MAXIMUM: **384K**" | <https://api-docs.deepseek.com/quick_start/pricing> | 2026-11-02 |
| 13 | Groq | llama-3.1-8b-instant | 목록표: "CONTEXT WINDOW (TOKENS) **131,072** / MAX COMPLETION TOKENS **131,072**" [5] | <https://console.groq.com/docs/models> | 2026-11-02 |
| 14 | xAI | grok-4-1-fast-non-reasoning | **확인 못 함** — 모델 페이지에 출력 한도 항목 없음(공개 항목: "Context window **2,000,000**", 가격) [6] | <https://docs.x.ai/docs/models/grok-4-1-fast-non-reasoning> | 2026-11-02 |
| 15 | xAI | chat completions `max_output_tokens` 미지정 시 | "**Defaults to 128,000 when unset**; set a larger value to allow longer generations." [7] | <https://docs.x.ai/docs/api-reference> | 2026-11-02 |
| 16 | Perplexity | sonar | **확인 못 함** — 현행 문서에 기본값·최대값 수치 없음 [8] | <https://docs.perplexity.ai/guides/model-cards> | 2026-11-02 |
| 17 | Perplexity | sonar-pro (참고) | "`sonar-pro` has a max output token limit of **8k**." | <https://docs.perplexity.ai/guides/model-cards> | 2026-11-02 |
| 18 | OpenRouter | `max_tokens` 미지정 시 동작 | "When a sampling parameter is absent from your request, **OpenRouter omits it upstream rather than substituting a hardcoded value, so the provider applies its own default**." | <https://openrouter.ai/docs/api_reference/parameters> | 2026-11-02 |
| 19 | OpenRouter | `max_tokens` 상한 | "Optional, integer, 1 or above … **The maximum value is the context length minus the prompt length.**" | (상동) | 2026-11-02 |
| 20 | OpenRouter | 모델별 상한 확인 방법 | GET `/api/v1/models` 응답의 `"top_provider": {"context_length": 8192, "is_moderated": true, "max_completion_tokens": 4096}` (문서 예시). 실측(2026-11-02): `deepseek/deepseek-chat` → `top_provider.max_completion_tokens` = **16000** (context_length 128000), `deepseek/deepseek-chat-v3.1` → **147456** | <https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties> | 2026-11-02 |
| 21 | HuggingFace Router | OpenAI 호환 라우터의 출력 토큰 한도 문서 | **확인 못 함(문서 부재)** — 라우터 문서 자체는 존재. 모델 메타데이터 관련 서술: "**GET `/v1/models` returns available models across all providers, including per-provider pricing, context length, latency, and throughput when available**" [9] | <https://huggingface.co/docs/inference-providers/index> | 2026-11-02 |

---

## 각주

**[1] Anthropic 레거시 모델.** 현행 문서의 모델 비교표는 최신 모델만 다룬다.
- `docs.claude.com/en/docs/about-claude/models/overview` — "Latest models comparison" 표: Sonnet 4.5 / Haiku 4.5 / Opus 4.1의 "Max output" = "64K tokens / 64K tokens / 32K tokens".
- `docs.claude.com/en/docs/about-claude/models/all-models` — 현행 세대 표: Claude Fable 5 / Opus 5 / Sonnet 5 = "128k tokens", Haiku 4.5 = "64k tokens".
- 요청한 레거시 모델(claude-3-5-sonnet, claude-3-5-haiku, claude-3-7-sonnet, claude-sonnet-4, claude-opus-4, claude-opus-4-5, claude-3-opus, claude-3-haiku)의 max output 수치는 현행 공식 문서 어디에도 없음.
- 생애주기 근거(`docs.claude.com/en/docs/about-claude/model-deprecations`): `claude-3-opus-20240229` "Deprecated … Tentative Retirement Date January 5, 2026", `claude-3-7-sonnet-20250219` "Deprecated … February 19, 2026", `claude-3-5-sonnet-*` 2025-08-13 공지로 2025-10-28 은퇴, `claude-3-haiku-20240307`/`claude-3-5-haiku-20241022`/`claude-sonnet-4-20250514`/`claude-opus-4-20250514` "Active" 표기. 단 "Active" 표기 여부와 무관하게 max output 수치는 미공개.

**[2] OpenAI.** `platform.openai.com/docs/api-reference/chat/create` 페이지는 본 조사 환경에서 렌더링되지 않아(404 응답), OpenAI 공식 OpenAPI 스펙(openai/openai-openapi 저장소 master 브랜치, 2026-11-02 스냅샷)으로 확인함.
- `max_completion_tokens` — description: "An upper bound for the number of tokens that can be generated for a completion, including visible output tokens and reasoning tokens." / type: `integer | null` / 기본값 문구 없음. (같은 스키마의 `frequency_penalty`에는 `default: 0`이 명시돼 있어, 스펙에 기본값 표기 규칙이 있음을 교차 확인 — 즉 이 파라미터에 기본 수치가 없는 것은 누락이 아니라 공시하지 않는 것.)
- 구형 `max_tokens` — description: "The maximum number of tokens that can be generated in the chat completion. This value can be used to control costs for text generated via API. This value is now deprecated in favor of `max_completion_tokens`, and is not compatible with o-series models." / type: `integer | null` / `deprecated: true` / 기본값 문구 없음.
- 결론: **생략 시 적용되는 기본 출력 상한 수치는 공식 문서에 공시돼 있지 않다**(negative finding).

**[3] Gemini.** `ai.google.dev/api/generate-content` 원문 HTML(2026-11-02 다운로드)에서 `maxOutputTokens`는 코드 예시(`maxOutputTokens: 20` 등)로만 등장하고 필드 기본값 설명문은 존재하지 않음(문구 "maximum number of output tokens" 원문 검색 0건). → 생략 시 기본값은 확인 불가.
- 모델별 상한 **조회 방법**은 문서화돼 있음: Model 리소스 필드 `outputTokenLimit` — "Maximum number of output tokens available for this model."(`https://ai.google.dev/api/models`, `models.get` 응답으로 조회).
- 통합 모델 목록 페이지(`ai.google.dev/gemini-api/docs/models`, "Last updated 2026-10-28 UTC")는 토큰 한도 열을 더 이상 포함하지 않음(원문 HTML에서 "output token" 문자열 0건 확인) — 수치는 개별 모델 상세 페이지(표 6~8행)에서만 공개됨.

**[4] DeepSeek.** 현행 API 레퍼런스의 `model` 가능값은 "`deepseek-v4-flash`, `deepseek-v4-pro`", Models & Pricing 문서의 소개 모델은 "`deepseek-flash`(DeepSeek-V4.1-Flash-1017로 서빙), `deepseek-v4-pro`" → **deepseek-chat은 현행 문서에 등재되지 않아 기본값/최대값 확인 불가**.
- 참고(과거 문서, 현행 아님): 2024-07 뉴스(`https://api-docs.deepseek.com/news/news0725`, deepseek-chat·deepseek-coder 대상) — "`max_tokens` is default to 4096. By enabling the Beta API, `max_tokens` can be set up to 8192".
- 모델별 최대 출력 **조회 방법**: List Models API 응답 필드 — "The maximum number of output tokens the server allows in a single response, i.e. the maximum accepted value of `max_tokens`."(`https://api-docs.deepseek.com/api/list-models`)

**[5] Groq.** 모델 목록표의 llama-3.1-8b-instant 행: 컨텍스트 131,072 / MAX COMPLETION TOKENS 131,072. 개별 모델 페이지(`console.groq.com/docs/model/llama-3.1-8b-instant`)의 "LIMITS" 섹션은 본 환경의 텍스트 추출에서 내용이 비어 있어, 목록표 값을 근거로 사용.

**[6] xAI 모델 페이지.** `grok-4-1-fast-non-reasoning` 페이지는 컨텍스트 창("Context window 2,000,000"), 가격(input $0.20 / output $0.50 per 1M tokens), 레이트리밋만 게시하며 최대 출력 토큰 항목이 없음. 페이지 원문 HTML에서도 "max output / max completion / output tokens" 관련 문자열 미확인(2026-11-02).

**[7] xAI API 레퍼런스.** `docs.x.ai/docs/api-reference` 페이지에 내장된 스키마에서 `max_output_tokens` 설명 2종 확인:
- chat completions 스키마: "Max number of tokens that can be generated in a response. Only applies to visible output tokens (i.e. does not apply to tokens used for reasoning or function calls). **Defaults to 128,000 when unset**; set a larger value to allow longer generations." (식별 근거: 인접 필드 `logprobs` — "Not supported by models `grok-4.20` and newer" — 가 models 개요 문서의 "Chat models" 주석과 일치)
- `/v1/responses` 스키마(인접 필드 `instructions` = "A system (or developer) message inserted into the model's context")의 동일 파라미터에는 기본값 문구 없음.

**[8] Perplexity.** Model cards(`docs.perplexity.ai/guides/model-cards`)의 sonar 행은 컨텍스트 길이("`sonar` | 128k")만 기술하고 출력 토큰 수치가 없다(출력 관련 유일 문구는 sonar-pro의 "max output token limit of 8k"). `docs.perplexity.ai/api-reference/chat-completions` 접속 시 Sonar Chat Completions 지원 종료 안내로 대체됨 — "Sonar Chat Completions support ended on September 27, 2026." → **sonar의 max_tokens 기본값/최대값은 현행 문서로 확인 불가**.
- 전환 참고(공식 마이그레이션 스킬, "when this skill and the live docs disagree on an API fact, the docs win" 명시): Sonar의 `max_tokens`/`max_completion_tokens`는 Agent API의 `max_output_tokens`로 매핑 — "REQUIRED when model is `anthropic/*` (else 400 …). Values under 16 are floored to 16." / Limits 표: "`max_output_tokens` | floor 16" (`https://github.com/perplexityai/api-platform-developers/blob/main/skills/migrate-sonar-to-agent-api/references/request-mapping.md`)

**[9] HuggingFace.** Inference Providers 문서는 OpenAI 호환 엔드포인트 `https://router.huggingface.co/v1/chat/completions` 사용법을 문서화한다. 그러나 모델별 **출력** 토큰 한도 문서는 확인되지 않음 — 문서가 언급하는 모델 메타데이터는 "GET `/v1/models` returns available models across all providers, including per-provider pricing, context length, latency, and throughput when available"이 전부다. (`huggingface.co/docs/router/...` 형태의 전용 Router 문서 페이지는 404로 존재하지 않음.)

---

## 조사 방법 및 한계

- **수집 방법**: 공식 문서 직접 패치(HTTP), OpenAI 공식 OpenAPI 스펙 다운로드 후 텍스트 추출, OpenRouter 공개 models API 실측(curl, 2026-11-02).
- **fetcher 누락 재검증**: 일부 페이지는 텍스트 추출기가 내용을 누락해, 원문 HTML을 내려받아 키워드 주변을 재추출해 확인했다 — DeepSeek create-chat-completion(기본값 문구), Gemini 개별 모델 페이지(Output token limit), xAI api-reference(스키마 문구), Gemini 통합 모델 페이지(수치 부재 확인), AI Studio/OpenAI developers 도메인(내용 미포함 확인).
- **확인 못 함 항목 재검색 이력**: 각 항목 2회 이상 다른 전략(사이트 내 검색, 스펙/원문 HTML 대조, 문서 색인 llms.txt 탐색, 유사 URL 추정)으로 재시도 후 수치 부재를 확인했다. 이후 문서 갱신 시 수치가 나타날 수 있으므로, 인용 수치는 반드시 확인일(2026-11-02) 기준으로 읽을 것.
- **미착수(범위 밖)**: 각 공급사 권장 `max_tokens` 설정값 도출, BYOK 경로 코드 수정안 — 본 문서는 공시 수치의 사실 확인만 다룬다.

---

## 코드 반영 (fix/byok-max-output-261102, 2026-11-02)

- apps/padiem-chat/app/byok_client.py의 Anthropic 직결 max_tokens는 이 문서의 공시 수치만 따른다: sonnet-4-5·haiku-4-5 64,000, opus-4-1 32,000, fable-5·mythos-5·opus-5·sonnet-5 128,000(가장 긴 패밀리 접두어 매칭). 표에 없는 모델(레거시 3.x/4.x 등 공시 부재 = 확인 못 함)은 기존 보수적 기본값 4,096을 유지한다.
- 연산자 덮개 PADIEM_BYOK_MAX_OUTPUT_TOKENS(기본 미설정)로 모델별 값을 덮을 수 있다. 잘못된 값(빈 값·정수 아님·0 이하)은 무시하고 기본 동작을 유지한다.
- OpenAI 호환·Google 와이어는 여전히 출력 한도를 전송하지 않는다(공급자 기본값) — 위 표 5·9·18~21행 근거.
- 세 와이어 모두 길이 제한 종료(openai finish_reason=length, anthropic stop_reason=max_tokens, gemini finishReason=MAX_TOKENS)에 잘림 안내를 덧붙인다.
