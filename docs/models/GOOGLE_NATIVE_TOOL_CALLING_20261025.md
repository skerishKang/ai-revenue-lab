# Google native tool calling — model support and evidence (2026-10-25, #4727)

This record separates three different claims that are easy to conflate:

1. what the **provider documents** for a model;
2. what the **B14 registry** enables for it (`apps/korean-ai-platform/app/pilot/b14_models.json`);
3. what the **B14 adapter** was proven to do locally (static/mock tests).

No live provider call was made for #4727. The CTO freeze forbids production
deployment and protected gates, and no new key or Secret change was requested;
the existing `PADIEM_B14_CREDENTIAL_05` binding is referenced by name only.

## Matrix

| Model | Provider documents function calling | B14 `tools` capability | B14 native wire | Live provider call |
|---|---|---|---|---|
| `google/gemini-3.1-flash-lite` | Supported (model page) | Enabled | First call + `functionResponse` follow-up + thought signature (mock-tested) | NOT RUN |
| `google/gemini-3.5-flash-lite` | Supported (model page) | Enabled | Same adapter path (mock-tested) | NOT RUN |
| `google/gemma-4-26b-a4b-it` | Documented on the Gemma-on-Gemini-API page (example uses this model) | Not enabled | Not offered: the registry gate refuses before dispatch | NOT RUN |
| `google/gemma-4-31b-it` | Documented on the Gemma-on-Gemini-API page | Not enabled | Not offered: the registry gate refuses before dispatch | NOT RUN |

Gemma is therefore **not implemented as tool-capable in B14**. The provider page
documents function calling, but the B14 registry does not enable the `tools`
capability, and no live native call was verified. Enabling it is an
owner-approved model-policy change and remains open.

## Provider evidence (read 2026-10-25)

- `https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite` —
  Function calling: Supported.
- `https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite` —
  Function calling: Supported.
- `https://ai.google.dev/gemini-api/docs/models/gemma` — supported Gemma models
  on the Gemini API (`gemma-4-31b-it`, `gemma-4-26b-a4b-it`) and a function
  calling example with `functionDeclarations`.
- `https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures` —
  Gemini 3 requires the signature on the first `functionCall` part, omits it on
  parallel calls, and requires all returned signatures to be echoed on a
  follow-up. OpenAI-compatible traffic carries the same value at
  `extra_content.google.thought_signature`.

## What the adapter now does

- Declared tools travel to `streamGenerateContent` as
  `tools[].functionDeclarations` with `parametersJsonSchema`; `tool_choice`
  maps to `toolConfig.functionCallingConfig`.
- An assistant `tool_calls` turn is translated to a `model` turn of
  `functionCall` parts, preserving call id, name and parsed arguments, plus the
  opaque `thoughtSignature` when one was issued.
- Each `role: tool` result is translated to a `functionResponse` part that
  answers its call by id and carries the result text verbatim under
  `response.result`. A result for an unknown call, a call left unanswered, a
  duplicated id, an undeclared historical tool name or non-object arguments is
  refused before dispatch.
- The native SSE call relays the signature as an optional `signature` on B14's
  `tool_call` event. It is not interpreted at any layer.
- The completed Google OpenAI-compatible lane maps B14's `signature` to
  `extra_content.google.thought_signature` on the way out and canonicalizes it
  back on the way in. Other providers never receive the field.
- The normal text lane keeps its exact request bytes: the signature field is
  present only when a provider issued one.

## Consumer boundary

Chat and Engine already receive the model-selected call through the existing
B14/Core stream contract and execute it through the existing Core/P01 plan and
step driver; the tool result reaches the model in that driver's follow-up and
the final answer is returned unchanged. This change keeps that behavior and
makes the B14 native follow-up contract available to a caller that replays the
exact call. Wiring a consumer to replay natively instead of using the existing
step-driver answer is the #5573 Chat/Engine boundary, not this adapter slice.

## Verification level

- Static contract and MockTransport tests:
  `apps/korean-ai-platform/tests/test_4727_google_native_roundtrip.py`,
  `apps/korean-ai-platform/tests/test_streaming_gateway.py`,
  `packages/padiem-ai-core/tests/test_tool_channel.py`,
  `packages/padiem-ai-core/tests/test_b14_streaming.py`.
- Live provider call: NOT RUN. The first live echo E2E remains a post-freeze
  step with the existing credential and route.
