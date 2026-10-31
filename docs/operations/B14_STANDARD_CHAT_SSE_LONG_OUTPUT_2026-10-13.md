# B14 standard chat streaming opt-in: long output without JSON buffer cap

The canonical POST /api/pilot/v1/chat/completions now delegates only
stream=true on an owner-registered manual Alpha model to the existing
independently validated SSE preview handler. No provider registration,
model ON/OFF, credential authority, BYOK or router setting changes.

- stream=false remains completed application/json and keeps its finite 8 MiB
  raw-body Worker memory guard. An unbounded json.loads + JSONResponse
  allocation is not safe under a shared 128MB Cloudflare Worker isolate.
- stream=true on a registered manual Alpha model produces text/event-stream
  chat.completion.chunk frames with business14 route metadata, a terminal
  data: [DONE], and bounded error semantics after output starts.
  Cumulative valid SSE output has no artificial byte limit; individual
  unfinished/oversized frames continue to be blocked to protect Worker RAM.
- The stream path reuses existing trusted schema/routing/auth checks and
  single-attempt/no-fallback boundary. The endpoint never silently promotes
  BYOK, b14/auto, unsupported structured content or fallback requests.
- The natural-HTTP-chunk handling has no chunk_size read-ahead latency.

Provider-free proof: one synthetic POST returns >8 MiB valid small SSE
frames on the canonical URL, delivers complete content and terminal DONE.
stream=false JSON, BYOK/auto/fallback refuses are independently tested.
B14 full suite and exact-head CI/GitGuardian must pass before deployment.

This is wire-level client opt-in, not an automatic format change. An existing
stream=false caller requesting greater than 8 MiB structured JSON must adopt
a compatible incremental protocol; simply deleting the Worker memory bound
would cause a potential memory exhaustion and denial of service.

## Optional P01/B14 tool-call events — #5573 slice 3-A (2026-10-24)

An explicit, nonempty `tools` declaration opts into the Google-only native
`streamGenerateContent?alt=sse` wire. Both the routed model's `tools` capability
and the Google wire are required, including on each existing fallback candidate.
Only `google/gemini-3.1-flash-lite` gains the capability in this slice; other
models, prices, provider selection and credentials remain unchanged.
[Google's model contract](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
declares function calling; the [native API](https://ai.google.dev/api/generate-content#method:-models.streamgeneratecontent)
accepts function declarations and `toolConfig.functionCallingConfig`.

- `tools` becomes `functionDeclarations` with `parametersJsonSchema`;
  `tool_choice` maps `auto/none/required` to `AUTO/NONE/ANY`, or a named function
  to `ANY` plus `allowedFunctionNames`. Absent choice/sampling/reasoning stays absent.
- Each complete native `functionCall` part produces an optional SSE event:
  `event: tool_call`, with JSON data containing `id`, `name`, `arguments`
  (a complete JSON-object string), and zero-based `index`. A missing native ID
  receives a per-stream unique ID. Partial/invalid/undeclared calls are refused.
- Tool-enabled streams terminate with `event: done` and JSON `finish_reason`:
  native `STOP` becomes `tool_calls` if calls exist, otherwise `stop`;
  `MAX_TOKENS` becomes `length`. Other text-only termination reasons are preserved.
  A missing finish or interrupted stream is an error, never successful `done`.
- Text chunks retain the existing `chat.completion.chunk` encoder. With tools
  omitted, null or empty, the upstream OpenAI-compatible request and all SSE
  bytes, including `data: [DONE]`, remain identical to the legacy path.
- A tool call commits the attempt just like visible text: no fallback after it.
  Consumers must receive successful `done` before executing calls; B14 itself
  executes no tool. Authentication, finite frame limits and stream cleanup remain.
- This slice accepts textual history only. Tool-result/thought-signature replay,
  Core/Chat consumption and PC entry are later slices; no new classification call.

Provider-free wire tests live in the existing `test_streaming_gateway.py` and
`test_streaming_provider.py`. This contract addition is not deployment/live proof.
