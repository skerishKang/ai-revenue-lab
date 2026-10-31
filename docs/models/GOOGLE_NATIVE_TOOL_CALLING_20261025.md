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

## Ledger interaction (the merged #5806 write path)

A declared tool changes which wire the call physically used and which counts the
provider reports, so the #5318 ledger row describes the request as it ran:

- `protocol` is `native` for a Google tool stream
  (`models/{model}:streamGenerateContent`) and stays `chat/completions` for the
  text lane. `native` is already in the stored vocabulary and its D1 `CHECK`, so
  this needs no migration.
- `usageMetadata.thoughtsTokenCount` is stored in the existing
  `reasoning_tokens` column instead of being dropped. `completion_tokens` stays
  exactly `candidatesTokenCount`: the thinking count is never folded into it, so
  a stored total that exceeds its parts is explained by a number the provider
  reported rather than by derived arithmetic.
- A completed tool call is visible output, so TTFT is measured on this lane, and
  the parent row still counts one logical request whatever the tool turn did.

## Known limits, stated rather than worked around

1. **A signature on a non-call part is not carried.** The cited provider page
   says a signature can attach to any part of the model turn while a follow-up
   must echo every signature that was returned. This channel carries one opaque
   value per tool call only, so a signature that arrived on a thinking or text
   part is dropped at the decoder and cannot be replayed. Closing it needs a
   turn-level field across the SSE frame, Core and Chat — the consumer boundary
   of #5573, not something the adapter can decide alone.
   **Closed by the follow-up slice** in
   `GOOGLE_THOUGHT_SIGNATURE_AND_TOOL_OUTCOME_20261025.md`: the answer text's own
   token now travels on the same event and returns on the part it signed. A
   thinking part's token stays where the reasoning text stays — not carried —
   because relaying that part was never this lane's contract.
2. **A refused or failed tool has no error channel.** `role: tool` carries text
   and nothing else, so the executor's refusal or failure reaches the model as
   result text. B14 never marks a call executed: it relays the call and the
   caller's own result.
   **Closed by the same follow-up slice**: a result can now carry the executor's
   own `ToolEvent` projection, and a non-completion is never written as a result.
3. **Unverified wire shapes.** Two behaviours of the native stream are tested
   only against frames this repo wrote: whether Gemini splits one
   `functionCall`'s arguments across frames (the decoder requires a complete,
   named call in a single part and refuses the stream otherwise) and whether
   `thinkingLevel` accepts every mapped `reasoning_effort` value. Both fail
   closed as `malformed_upstream_response` or a provider 4xx, never as a
   partial call. The first live echo has to confirm them.

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
  `apps/korean-ai-platform/tests/test_4727_google_native_roundtrip.py` (the
  replay is driven through the streaming route, so the outbound native body and
  the returned answer are both observed),
  `apps/korean-ai-platform/tests/test_5318_b14_call_ledger.py` (the tool stream's
  protocol and thinking counts as stored),
  `apps/korean-ai-platform/tests/test_streaming_gateway.py`,
  `packages/padiem-ai-core/tests/test_tool_channel.py`,
  `packages/padiem-ai-core/tests/test_b14_streaming.py`.
- Live provider call: NOT RUN. The first live echo E2E remains a post-freeze
  step with the existing credential and route.
