# Padiem AI Core

Internal shared AI execution contracts and bounded product-neutral capabilities for Padiem products.

## Ownership boundary

```text
Padiem product
  -> product adapter
  -> Padiem AI Core shared contracts/runtime
  -> Business 14 model execution foundation
```

Business 14 owns provider access, provider credentials, model catalog/routing and exact upstream execution. Product surfaces own product state, UX, Projects/history and user-facing policy. Core normalizes reusable execution capabilities between those layers and must not become a second model router.

## Shared contracts

- `Evidence` — product-neutral provenance/evidence metadata.
- `ToolSpec` — schema, ownership, side-effect, authorization and approval contract for a tool.
- `AgentProfile` — product-neutral agent instruction and execution-policy contract.
- `RunMetadata`, `ToolEvent`, `UsageMetadata` — shared trace/observability metadata.
- explicit enums for side effects, approval, run state and error classification.

## Read-only Web Runtime

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

## Business 14 execution transport

The shared B14 client is a transport boundary, not a second router:

```text
B14ExecutionConfig
B14RoutingOptions
B14ChatRequest
B14MultimodalChatRequest
B14RouteMetadata
B14ExecutionResult
B14ExecutionError
B14ExecutionClient
B14StreamingClient
```

Responsibilities:

- validate a configured B14 origin and bounded timeout/response cap;
- serialize the current B14 request contracts;
- call fixed B14 endpoints through bounded transports;
- disable redirects and cap response bodies;
- normalize timeout, transport, authorization, rate-limit, request and server failures;
- extract assistant text plus an allowlisted subset of B14 route metadata;
- preserve standard token usage only when valid;
- validate the current bounded image contract for JPEG/PNG/WebP data URLs;
- never reflect raw upstream error bodies or image payloads in safe errors.

The current low-level multimodal boundary allows one image per multimodal message, validates image magic against media type, caps decoded image bytes at 4 MiB, and freezes/copies caller-owned message data.

Non-responsibilities:

- no provider selection or Router Core logic;
- no client-side provider/model fallback policy beyond product-supplied normalized policy;
- no Provider/BYOK credential forwarding in Core request contracts;
- no Padiem Chat `Skill`, Korean UX copy, attachment type, quota/auth/history/project logic.

## Higher-level Execution Runtime

Ordinary completed and streaming model execution now use product-neutral runtime facades:

```text
AgentProfile + ExecutionRequest
  -> ExecutionRuntime
  -> B14ChatRequest
  -> B14ExecutionClient

AgentProfile + ExecutionRequest
  -> StreamingExecutionRuntime
  -> B14 streaming transport
```

Core owns:

- exactly one server-owned composed system instruction;
- bounded optional additional system context;
- product-neutral model/routing-policy normalization;
- request/result contract validation;
- route/usage/run metadata normalization;
- safe shared error mapping;
- no automatic retry or hidden Provider fallback.

Caller-supplied `system` messages are rejected. Product state and user-facing error copy remain outside Core.

## Bounded Multimodal Execution Runtime

Issue #1068 adds the matching higher-level non-streaming facade for the already supported one-image transport contract:

```text
AgentProfile + MultimodalExecutionRequest
  -> MultimodalExecutionRuntime
  -> B14MultimodalChatRequest
  -> B14ExecutionClient
```

The facade intentionally reuses the existing B14 multimodal validator instead of creating a second image parser. It preserves:

- JPEG / PNG / WebP base64 data URLs only;
- exactly one image for the higher-level execution request;
- decoded image cap of 4 MiB;
- bounded message/part/text counts;
- user/assistant product history only — no caller `system` role;
- Core-owned system composition and model-policy normalization;
- the same `ExecutionResult`, `RunMetadata` and `ExecutionRuntimeError` semantics as text completion;
- zero Provider/model selection in Core.

This slice is non-streaming because the current product requirement is non-streaming image completion. It does not widen the product to multiple images, audio, video or model-native tools.

## Grounding / research runtime

Core also contains the reusable grounding/research orchestration primitives used by product adapters. These normalize bounded evidence/context and research progress while leaving search presentation and product UX outside Core.

## Permission-gated Tool Runtime

The Tool Runtime executes only server-registered handlers after a fail-closed policy sequence:

```text
ToolAuthorizationContext
ToolInvocation
ToolHandler
ToolExecutionResult
ToolRuntimeError
ToolRuntime
```

Execution gate:

```text
registered tool
  -> authorization agent matches AgentProfile
  -> tool is in AgentProfile.allowed_tools
  -> owner is core or matches app_id
  -> every ToolSpec.auth_scope is granted
  -> ToolSpec approval policy is satisfied
  -> arguments pass JSON + Draft 2020-12 schema validation
  -> async handler executes exactly once
  -> output passes JSON + size boundary
```

The model-proposed invocation contains only `tool_id` and `arguments`. It cannot grant itself tools, auth scopes, user confirmation, external authorization, ownership or handler code. Those values come from trusted server/product-adapter state.

Security and execution invariants:

- denied or invalid calls execute the registered handler zero times;
- `USER_CONFIRMATION` and `EXTERNAL_AUTHORIZATION` are exact per-tool grants, not global booleans;
- product-owned tools cannot cross application ownership boundaries;
- `owner=core` is the explicit shared-tool boundary;
- invalid JSON Schema is rejected at registration;
- arguments are copied/frozen, JSON-only, finite-number-only and capped at 64 KiB;
- handlers receive an isolated mutable copy;
- handlers are async and run once with `ToolSpec.timeout_seconds`;
- no automatic retry is performed;
- handler exception text is not reflected in safe errors;
- output is JSON-only, finite-number-only, copy-isolated and capped at 256 KiB;
- success and failure use the existing `ToolEvent`, `RunStatus` and `ErrorClass` contracts.

This runtime is not yet wired to a model-native function-call protocol.

## Secret boundary

- `WebRuntimeConfig.firecrawl_api_key` is server-side configuration and excluded from `repr`/public serialization.
- B14 execution clients contain no provider key and do not forward arbitrary Provider credentials.
- Tool authorization contains identifiers/scopes/approval markers only, never credential values.
- Tool handler and execution transport exception text is normalized rather than exposed.
- Tests use mock/in-process handlers and transports; no live provider credential is required.

## Current integration status

Completed and accepted before #1068:

- Padiem Chat ordinary completion through `ExecutionRuntime`;
- Padiem Chat ordinary streaming through `StreamingExecutionRuntime`;
- reusable grounding/deep-research orchestration;
- Core ↔ B14 execution-contract lock;
- Living Learning reuse of the shared Core execution contract.

Issue #1068 closes the documented B62 image-path exception by moving high-level image execution assembly into Core while preserving B62's product-owned image-capability fail-closed gate.

## Still deliberately deferred

- model-native tool/function-call protocol;
- Agent execution loop/autonomous orchestration;
- product-specific tool adapters;
- write-capable browser actions;
- multimodal streaming;
- multiple-image, audio or video expansion;
- memory/RAG;
- user-facing approval UI;
- remote/MCP tool registry;
- Provider/model selection for B62 LOW/MEDIUM/HIGH;
- Production re-arm.

Current B62 model-profile state remains:

```text
LOW = UNASSIGNED
MEDIUM = UNASSIGNED
HIGH = UNASSIGNED
MODEL_SELECTION = DEFERRED
#913 = HOLD
```

Authorities: #993, #1008, #1009, #1011, #1068 and the earlier Core slice issues #809, #811, #814, #819.
