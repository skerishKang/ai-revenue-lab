# Reference Board

Capture date: 2026-08-02

This board records screen-level patterns. No third-party brand art, protected illustration, screenshot or copy is included in the runtime.

## Direct products

### OpenRouter — Models and Chat Playground

- URLs: `https://openrouter.ai/models`, `https://openrouter.ai/chat`
- Pattern studied: searchable model discovery; filters and sort near the list; immediate add-model action; routed response identifies the model that answered.
- Adopt: model discovery before administration; one clear model selector; route identity after response.
- Reject: copying brand, dark palette, model logos or exact layout.
- Business 14 improvement: Korean purpose presets and explicit domestic/local/external route classes.
- Corresponding states: `모델`, `시작`, `자동 경로`.

### Vercel AI Gateway — Model detail and Playground

- URL: `https://vercel.com/ai-gateway/models`
- Pattern studied: model capability, provider information, code sample and playground remain close together.
- Adopt: model detail should answer “what is this, can I use it, how do I call it?” without forcing several pages.
- Reject: team billing assumptions and brand-specific black/white imitation.
- Business 14 improvement: Provider-key readiness and route reason appear in the same model surface.
- Corresponding state: `모델 상세`.

### Cloudflare AI Gateway — First-run onboarding

- URL: `https://developers.cloudflare.com/ai-gateway/`
- Pattern studied: reveal the OpenAI-compatible endpoint early; give explicit next actions when no requests exist; consolidate code-example choices.
- Adopt: endpoint, SDK and authentication selectors in one focused area.
- Reject: infrastructure account hierarchy as the personal home.
- Business 14 improvement: first request can be tried before visiting analytics.
- Corresponding states: `시작`, `개발자`.

### Requesty — Unified gateway and BYOK

- URLs: `https://www.requesty.ai/gateway`, `https://docs.requesty.ai/features/bring-your-own-keys`
- Pattern studied: one base URL, broad model access and Provider keys presented as one product story.
- Adopt: connected Provider clearly explains which models become usable.
- Reject: organization and sales framing as the initial interface.
- Business 14 improvement: personal Korean guidance and local route visibility.
- Corresponding state: `Provider 키`.

### Portkey and LiteLLM — Gateway operations

- URLs: `https://portkey.ai/docs/product/ai-gateway`, `https://docs.litellm.ai/`
- Pattern studied: fallback, retries, virtual keys, budgets and observability.
- Adopt later: route evidence and bounded fallback disclosure.
- Reject now: admin-dense default dashboard and enterprise control vocabulary.
- Corresponding states: `자동 경로`, `활동`.

## Visual and interaction references

### Linear — calm density

- URL: `https://linear.app/now/behind-the-latest-design-refresh`
- Pattern studied: quieter surfaces, consistent hierarchy, scan-first lists and keyboard speed.
- Adopt: reduce visual containers; make active context obvious; keep metadata secondary.
- Reject: copying navigation details or theme.

### Vercel Web Interface Guidelines

- URL: `https://vercel.com/design/guidelines`
- Pattern studied: visible focus, no dead ends, precise labels, 44 px mobile targets, 16 px mobile inputs, error messages that show the exit.
- Adopt: technical UI floor and restrained code presentation.

### Raycast — command/search first

- URL: `https://www.raycast.com/faq`
- Pattern studied: one fast input gives access to broad capability; keyboard hints appear contextually.
- Adopt: the Start screen begins with one dominant intent field and purpose presets.
- Reject: desktop command-palette imitation on mobile.

### Stripe developer surfaces

- URL: `https://docs.stripe.com/`
- Pattern studied: code remains close to the action; secrets are treated as one-time values; request IDs support debugging.
- Adopt: endpoint/code copy and clear Provider-key state.
- Reject: payments-specific dashboard grammar.

## Original advantage

The reference set mostly separates model browsing, key setup, playground and route evidence. Business 14 combines them around one visible `Route Trace`:

```text
사용 목적
→ 제약과 선호
→ 가능한 경로
→ 선택 모델 / Provider
→ 요청 결과
→ 복사 가능한 endpoint
```

The product does not claim a universal best model. It makes a bounded selection understandable to a Korean individual.