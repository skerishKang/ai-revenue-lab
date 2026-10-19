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
