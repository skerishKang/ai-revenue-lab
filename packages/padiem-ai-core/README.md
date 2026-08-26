# Padiem AI Core

Internal shared AI runtime contracts and bounded capabilities for Padiem products.

## Ownership boundary

```text
Padiem product
  -> product adapter (later)
  -> Padiem AI Core shared contracts/runtime
  -> Business 14 model execution foundation (existing)
```

Business 14 remains the owner of provider access, Router Core, provider adapters and model execution. Padiem Chat remains a product/reference client.

## Shared contracts — Slice 1

- `Evidence` — product-neutral provenance/evidence metadata.
- `ToolSpec` — schema, ownership, side-effect, authorization and approval contract for a tool.
- `AgentProfile` — product-neutral agent instruction and execution-policy contract.
- `RunMetadata`, `ToolEvent`, `UsageMetadata` — shared trace/observability metadata.
- explicit enums for side effects, approval, run state and error classification.

## Read-only Web Runtime — Slice 2

The first executable shared capability is intentionally narrow:

```text
WebRuntimeConfig
WebProvider
OffWebProvider
MockWebProvider
FirecrawlWebProvider
normalize_public_url
create_web_provider
```

The runtime uses the Slice 1 `Evidence` contract rather than creating a product-local evidence type.

### Security boundary

- only literal public `http`/`https` URLs are accepted;
- localhost, internal suffixes, non-global literal IPs, userinfo and ambiguous numeric host forms are rejected;
- IDNA hostnames are normalized and URL fragments removed;
- query, result, title, snippet, URL and provider-response sizes are bounded;
- Firecrawl uses a fixed provider origin and only `/v2/search` and `/v2/scrape`;
- provider redirects are disabled;
- returned evidence URLs are revalidated;
- safe errors never reflect provider response bodies or API keys;
- Off and Mock providers make zero network calls.

`normalize_public_url` is a literal-host policy and does not perform DNS resolution. This Slice therefore does not claim DNS-rebinding protection. The implemented network provider calls only the fixed Firecrawl origin and sends target URLs as request data.

### Secret boundary

`WebRuntimeConfig.firecrawl_api_key` is server-side configuration. It is excluded from dataclass `repr` and public serialization. The package contains no provider key and tests use only `httpx.MockTransport` fixtures.

## Still deliberately deferred

- Padiem Chat import rewiring;
- Business 14 client extraction;
- model-output streaming;
- model tool/function calling;
- Agent execution loop;
- write-capable browser actions;
- direct arbitrary-site HTTP/browser fetching;
- grounding/deep research orchestration;
- memory/RAG;
- product adapters.

Authorities: GitHub Issues #809 and #811.
