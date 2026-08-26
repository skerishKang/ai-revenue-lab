# Padiem AI Core

Internal shared AI runtime contracts and bounded capabilities for Padiem products.

## Ownership boundary

```text
Padiem product
  -> product adapter
  -> Padiem AI Core shared contracts/runtime
  -> Business 14 model execution foundation
```

Business 14 remains the owner of provider access, Router Core, provider adapters and model execution. Padiem Chat remains a product/reference client until a later explicit integration slice.

## Shared contracts — Slice 1

- `Evidence` — product-neutral provenance/evidence metadata.
- `ToolSpec` — schema, ownership, side-effect, authorization and approval contract for a tool.
- `AgentProfile` — product-neutral agent instruction and execution-policy contract.
- `RunMetadata`, `ToolEvent`, `UsageMetadata` — shared trace/observability metadata.
- explicit enums for side effects, approval, run state and error classification.

## Read-only Web Runtime — Slice 2

```text
WebRuntimeConfig
WebProvider
OffWebProvider
MockWebProvider
FirecrawlWebProvider
normalize_public_url
create_web_provider
```

The runtime uses the shared `Evidence` contract rather than creating a product-local evidence type.

Security boundary:

- only literal public `http`/`https` URLs are accepted;
- localhost, internal suffixes, non-global literal IPs, userinfo and ambiguous numeric host forms are rejected;
- IDNA hostnames are normalized and URL fragments removed;
- query, result, title, snippet, URL and provider-response sizes are bounded;
- Firecrawl uses a fixed provider origin and only `/v2/search` and `/v2/scrape`;
- provider redirects are disabled;
- returned evidence URLs are revalidated;
- safe errors never reflect provider response bodies or API keys;
- Off and Mock providers make zero network calls.

`normalize_public_url` is a literal-host policy and does not perform DNS resolution. This does not claim DNS-rebinding protection.

## Business 14 execution client — Slice 3

The shared B14 client is a transport boundary, not a second router:

```text
B14ExecutionConfig
B14RoutingOptions
B14ChatRequest
B14RouteMetadata
B14ExecutionResult
B14ExecutionError
B14ExecutionClient
```

Responsibilities:

- validate a configured B14 origin and bounded timeout/response cap;
- serialize the current B14 chat request contract;
- call the fixed `/api/pilot/v1/chat/completions` endpoint once;
- disable redirects and cap the streamed response body;
- normalize timeout, transport, authorization, rate-limit, request and server failures;
- extract assistant text plus an allowlisted subset of B14 route metadata;
- preserve standard token usage only when valid;
- never reflect raw upstream error bodies.

Non-responsibilities:

- no provider selection or Router Core logic;
- no client-side provider/model fallback;
- no Provider/BYOK credential forwarding in the Slice 3 contract;
- no Padiem Chat `Skill`, Korean UX copy, attachment type, quota/auth/history/project logic;
- no streaming, tools or agent loop.

Business 14 remains the authority that decides the route and executes provider calls. Product adapters prepare system instructions, messages, capabilities and user-facing failure copy before/after the Core transport call.

## Secret boundary

- `WebRuntimeConfig.firecrawl_api_key` is server-side configuration and excluded from `repr`/public serialization.
- The B14 execution client contains no provider key or Authorization field and does not forward such headers by default.
- Tests use only `httpx.MockTransport`; no live provider credential is required.

## Still deliberately deferred

- Padiem Chat import rewiring;
- model-output streaming;
- model tool/function calling;
- Tool Runtime;
- Agent execution loop/orchestration;
- write-capable browser actions;
- grounding/deep research orchestration;
- memory/RAG;
- product-specific adapters.

Authorities: GitHub Issues #809, #811 and #814.
