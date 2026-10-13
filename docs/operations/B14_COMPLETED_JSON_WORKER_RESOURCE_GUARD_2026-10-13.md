# B14 completed JSON memory guard vs model output capacity (2026-10-13)

## Owner-approved technical classification

**Do not impose a PADIEM-specific provider token/generation ceiling.** The
caller may omit `max_tokens` to delegate to the upstream vendor/model. Keep
authentication, explicit product/model enable flags and genuine server resource
safety independent of vendor token capacity.

Cloudflare Workers impose **128 MB per isolate**, shared by concurrent
requests, including WebAssembly and JS heaps. The platform does **not** impose
a fixed response-body size limit. A Python completed-JSON adapter, however,
returns one materialized `dict` and cannot safely promise unbounded body
collection, decoding and response serialization within that isolate.
Source: https://developers.cloudflare.com/workers/platform/limits/

## Current effective byte guards (after #4379)

| Data path | Effective guard | Reason |
|---|---:|---|
| Generic completed-JSON success | **8 MiB** raw decoded upstream HTTP bytes | Conservative finite Worker memory budget |
| OpenCode Go completed-JSON success | **8 MiB** | Same collector and post-parse budget |
| Legacy BYOK completed-JSON success | **8 MiB** | Same collector and post-parse budget |
| Generic upstream error body | **1 MiB** | Untrusted diagnostics, not model answer |
| Generic & Go SSE individual/incomplete frame | **1 MiB** | Bound temporary frame buffer, not total generation |
| SSE cumulative valid events | **No PADIEM aggregate byte cap** | Process frames incrementally, never truncate valid output |

The **8 MiB budget is NOT the upstream model's output-token capacity**. It
is a safety budget for in-memory completed JSON. At cap+1 byte the existing
`upstream_response_too_large` classification is explicit, not silent
truncation; no retry/fallback is introduced. The former 1 MiB completed-JSON
rejection was unnecessarily shared with the error/SSE budget and has been
removed, without dropping the Worker resource guard. Normal large free-form
outputs should use SSE rather than requesting a single completed JSON object.

The legacy `b14_runtime_config.max_response_bytes = 1 MiB` is **not wired**
to any collector. Operator metadata now explicitly declares
`max_response_bytes_effect=no` alongside both effective resource budgets;
changing that field does not silently change safety.

## Bounded synthetic acceptance evidence

- Existing caller + one physical synthetic upstream POST per request.
- Valid 2 MiB text answer accepted *verbatim* by generic, Go and BYOK adapters.
- Exact **8 MiB complete JSON** accepted *verbatim* by the generic adapter.
- Cap+1 and a dishonestly low `Content-Length` are rejected based on actual
  received bytes before the buffer grows past the completed budget.
- Generic error-body guard remains 1 MiB; SSE no read-ahead/latency regression.
- Source uses pre-append `bytearray` guard; `json.loads` creates an in-memory
  object and `_response_bytes` reflects the collected raw body length.
- Isolated CPython 3.11 trace with ~8 MiB ASCII answer: **24.0 MiB**
  `tracemalloc` peak for the collector + JSON parse (preconstructed synthetic
  transport payload excluded). This does **not** include Cloudflare Pyodide,
  WebAssembly, JS allocations, concurrent requests or serialization; it is
  *not* a 128 MB Worker memory safety certification.
- No live paid provider call or model/tier/credential activation was required.

## Why the remaining finite guard is legitimate

Workers cannot return arbitrarily large completed JSON `dict` objects under
a 128 MB per-isolate memory limit with no reservation for concurrent calls.
An automatic switch from `stream=false` to a different SSE response format
would break clients and must not be introduced silently. Changing the
resource guard beyond this conservative initial 8 MiB requires production
memory/overload measurements or genuine incremental JSON materialization and
a compatible upstream/downstream wire contract. The resource guard must
never masquerade as a provider model-native token ceiling.
