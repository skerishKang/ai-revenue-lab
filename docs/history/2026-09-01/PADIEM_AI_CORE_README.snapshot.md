# Padiem AI Core

Internal shared AI execution contracts and bounded product-neutral capabilities for Padiem products.

Authority: #1101, #1315 and `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`.

## Ownership boundary

```text
Padiem product
  -> product/domain adapter
  -> Padiem AI Core shared contracts/runtime
  -> Padiem AI Engine when a cross-runtime service boundary is required
  -> Business 14 model execution foundation
```

Business 14 owns inference provider access, provider credentials, model catalog/routing, fallback and exact upstream execution. Product surfaces own product state, UX, Projects/history, domain locators and user-facing policy. Padiem AI Engine owns the internal service/API projection of Core semantics. Core normalizes reusable execution, grounding, context, permission, memory/RAG, tool, skill, agent, evidence and orchestration semantics between those layers and must not become a product UI/domain model or a second model router.

## Capability status vocabulary

This README distinguishes source capability from runtime activation:

```text
IMPLEMENTED_CORE_PRIMITIVE       reusable Core semantic contract/runtime exists on current main
INTEGRATED_CONSUMER_PATH         at least one accepted product/service path consumes the Core primitive
ENGINE_PROJECTION_DEFERRED       Core exists, but the Engine service projection remains deferred/unavailable
PRODUCTION_ACTIVATION_DEFERRED   no Production/runtime activation is implied by code presence
FUTURE_DEFERRED                  explicitly not implemented or not in this slice
UNKNOWN_PENDING                  not proven from current main and accepted issue/PR evidence
```

`CODE_ON_MAIN` or `IMPLEMENTED_CORE_PRIMITIVE` does not by itself mean a live provider, credential, database, product flag, public endpoint or Production deployment is active.

## Required capability classification for future Core work

Every AI/harness PR touching Core, Engine, B14, B61 or B62 should state the #1315 classification before implementation:

```text
CAPABILITY_OWNER = B61 | B62 | CORE | ENGINE | B14 | OTHER
CAPABILITY_CLASS = REUSE_CORE | EXTEND_CORE | PRODUCT_ADAPTER | B14_EXECUTION | ENGINE_TRANSPORT | DO_NOT_SHARE
REUSE_AUDIT = <existing issues/files/contracts checked>
OVERLAP_WITH = <issue/file list or NONE>
CORE_PROMOTION_REQUIRED = YES | NO
CONTRACT_IMPACT = NONE | BACKWARD_COMPATIBLE | BREAKING
PRODUCT_SPECIFIC_SEMANTICS_IN_CORE = 0
GENERIC_CORE_DUPLICATION_IN_PRODUCT = 0
```

## Shared contracts

Status: `IMPLEMENTED_CORE_PRIMITIVE`.

- `Evidence` — product-neutral provenance/evidence metadata.
- `ToolSpec` — schema, ownership, side-effect, authorization and approval contract for a tool.
- `AgentProfile` — product-neutral agent instruction and execution-policy contract.
- `RunMetadata`, `ToolEvent`, `UsageMetadata` — shared trace/observability metadata.
- explicit enums for side effects, approval, run state and error classification.

Products may project these contracts into UI, but they must not redefine the generic authority semantics.

## Read-only Web Runtime

Status: `IMPLEMENTED_CORE_PRIMITIVE`; provider activation and credentials remain server-side gates.

```text
WebRuntimeConfig
WebProvider
OffWebProvider
MockWebProvider
FirecrawlWebProvider
DaumWebProvider
normalize_public_url
create_web_provider
```

The runtime uses the shared `Evidence` contract rather than creating a product-local evidence type.

Security boundary:

- only literal public `http`/`https` URLs are accepted;
- localhost, internal suffixes, non-global literal IPs, userinfo and ambiguous numeric host forms are rejected;
- IDNA hostnames are normalized and URL fragments removed;
- query, result, title, snippet, URL and provider-response sizes are bounded;
- Firecrawl uses a fixed provider origin and bounded search/scrape paths;
- Daum web search is a Core provider contract but live public use remains gated by terms/activation decisions;
- provider redirects are disabled where applicable;
- returned evidence URLs are revalidated;
- safe errors never reflect provider response bodies or API keys;
- Off and Mock providers make zero network calls.

`normalize_public_url` is a literal-host policy and does not perform DNS resolution. This does not claim DNS-rebinding protection.

## Business 14 execution transport

Status: `IMPLEMENTED_CORE_PRIMITIVE`; B14 remains the inference execution authority.

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

Non-responsibilities:

- no provider selection or Router Core logic;
- no client-side provider/model fallback policy beyond product-supplied normalized policy;
- no Provider/BYOK credential forwarding in Core request contracts;
- no Padiem Chat `Skill`, Korean UX copy, attachment type, quota/auth/history/project logic.

## Higher-level execution runtimes

Status: `IMPLEMENTED_CORE_PRIMITIVE`; accepted consumer paths exist for ordinary completed/streaming execution.

Ordinary completed and streaming model execution use product-neutral runtime facades:

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

## Bounded multimodal execution runtime

Status: `IMPLEMENTED_CORE_PRIMITIVE`; non-streaming one-image high-level facade only.

```text
AgentProfile + MultimodalExecutionRequest
  -> MultimodalExecutionRuntime
  -> B14MultimodalChatRequest
  -> B14ExecutionClient
```

The facade reuses the existing B14 multimodal validator instead of creating a second image parser. It preserves:

- JPEG / PNG / WebP base64 data URLs only;
- exactly one image for the higher-level execution request;
- decoded image cap of 4 MiB;
- bounded message/part/text counts;
- user/assistant product history only — no caller `system` role;
- Core-owned system composition and model-policy normalization;
- the same `ExecutionResult`, `RunMetadata` and `ExecutionRuntimeError` semantics as text completion;
- zero Provider/model selection in Core.

Multimodal streaming and multiple-image/audio/video expansion remain `FUTURE_DEFERRED`.

## Grounding, search decision and research runtime

Status: `IMPLEMENTED_CORE_PRIMITIVE`; B62 currently consumes parts of this through product adapters.

Core contains reusable grounding/research orchestration primitives that normalize bounded evidence/context and research progress while leaving search presentation and product UX outside Core.

Current Core anchors include:

```text
search_decision.py
search_preparation.py
source_quality.py
grounding_runtime.py
GroundedResearchRuntime
```

Current semantics:

- automatic search disposition is shared Core policy, not a second product-local decision engine;
- search preparation produces bounded provider-neutral evidence acquisition requests;
- #1308 Source Trust + Relevance selects relevant/source-appropriate evidence before synthesis;
- grounded synthesis uses bounded evidence/citation context;
- web evidence is untrusted data, not instruction authority;
- search/fetch/deep-research product presentation remains outside Core.

## Context permission and knowledge boundary

Status: `IMPLEMENTED_CORE_PRIMITIVE` after #1313.

Core owns the product-neutral permission/knowledge-boundary gate for one model turn:

```text
ContextEnvelope
KnowledgeBoundary
ContextCandidate
FilteredContext
ContextPermissionProjection
BoundaryDisposition
ContextFilterReason
project_context_permission
context_envelope_from_source_selection
candidate_from_evidence
narrow_knowledge_boundary
```

Ordering for externally retrieved evidence:

```text
provider retrieval
  -> Source Trust + Relevance selection (#1308)
  -> Context Permission + Knowledge Boundary filtering (#1313)
  -> grounding/context assembly
  -> model invocation
```

Core enforces:

- `MODEL_KNOWS_X != MODEL_MAY_USE_X`;
- relevant/trusted evidence may still be filtered if outside the trusted boundary;
- `SourceQualitySelection` is consumed without re-ranking or resurrecting rejected evidence;
- filtered context must not reach the model prompt/context;
- user self-asserted permission cannot widen the trusted boundary;
- product adapters may narrow Core policy but cannot disable mandatory fail-closed behavior;
- bounded diagnostics do not expose private corpus bytes, secrets or hidden policy text.

B61 owns StoryMemory reader locators, reading progress, annotations, knowledge-ceiling value and spoiler UX. B62 owns product request/session/presentation context. Core consumes normalized product adapter output only.

## Permission-gated Tool Runtime

Status: `IMPLEMENTED_CORE_PRIMITIVE`; model-native function-call protocol remains `FUTURE_DEFERRED`.

The Tool Runtime executes only server-registered handlers after a fail-closed policy sequence:

```text
ToolAuthorizationContext
ToolInvocation
ToolHandler
ToolExecutionResult
ToolRuntimeError
ToolRuntime
ToolRegistry
ConnectorRegistry
ToolResourcePolicy
ToolLifecycle
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

## Memory / RAG semantics

Status: `IMPLEMENTED_CORE_PRIMITIVE`; product storage/backend and Engine projection are separate.

Core defines product-neutral memory and retrieval semantics without owning product persistence:

```text
retrieval.py
memory.py
memory_read.py
memory_receipt.py
memory_context.py
```

Implemented Core responsibilities include:

- namespace and authorization contracts for memory read/write;
- write receipt and idempotency semantics;
- bounded retrieval context assembly;
- retrieval ranking/long-context preparation;
- fail-closed behavior for missing authority or malformed inputs.

Products or storage adapters remain responsible for actual persistence, domain-specific retrieval candidates and corpus locator meaning. B14 must not query product memory stores directly.

## Evidence / verification semantics

Status: `IMPLEMENTED_CORE_PRIMITIVE`.

Core defines reusable evidence and verification contracts:

```text
evidence_graph.py
evidence_verification.py
evidence_citation.py
evidence_assessment.py
```

Implemented Core responsibilities include:

- source/provenance identity and derivation links;
- claim-to-source relationship modeling;
- observed/inferred/unverified/verified status semantics;
- product-neutral verification hooks;
- grounded citation projection;
- contradiction and missing-evidence representation;
- unknown confidence remains unknown unless proven.

Model claims do not self-verify, and human approval remains a separate authority.

## Skill runtime semantics

Status: `IMPLEMENTED_CORE_PRIMITIVE`.

Core owns reusable skill package/version/registry/activation semantics:

```text
skill_* modules
```

Current Core responsibilities include:

- skill package identity and version compatibility;
- trusted registry/install/enable state;
- activation and compilation constraints;
- product-neutral input/output/context/model policy boundaries.

B62 TaskModes and product-facing presets are not Core Skills. Products may adapt UI selections into Core skill contracts only where the shared contract is active.

## Agent and orchestration semantics

Status: `IMPLEMENTED_CORE_PRIMITIVE`; some Engine projections and live product integrations remain separately gated.

Current Core anchors include:

```text
agent_definition.py
agent_profile_adapter.py
agent_planner.py
agent_approval.py
agent_delegation.py
agent_recovery.py
agent_events.py
agent_execution_bridge.py
orchestration.py
orchestration_events.py
adapter_conformance.py
```

Implemented Core semantics include:

- agent definition/profile compilation;
- bounded planning/runtime policy;
- approval pause/resume semantics;
- delegation, recovery and normalized events;
- plan-backed agent execution bridge;
- orchestration runner/events composing context, memory, agent, skill, tool and evidence primitives;
- adapter conformance expectations.

Engine transports orchestration endpoints where accepted. Engine health/manifest must truthfully distinguish available, deferred and unavailable projections. Product UI/copy and product adapters remain outside Core.

## Execution context, cancellation and idempotency

Status: `IMPLEMENTED_CORE_PRIMITIVE`; durable/server adapter wiring can remain separately gated.

Core defines execution context semantics including trace, timeout, cancellation and idempotency boundaries:

```text
execution_context.py
execution_state_machine.py
contextual_execution.py
```

Current semantics include:

- trace identity is observability, not authorization;
- timeout/cancellation propagation is explicit;
- cancellation is not converted to generic retry;
- idempotency key is not authorization;
- same-key/same-request replay requires an injected trusted adapter;
- same-key/different-request fails closed;
- missing durable adapter fails closed rather than using fake process-local Production truth.

## Secret and private-payload boundary

- `WebRuntimeConfig.firecrawl_api_key` and Daum/search credentials are server-side configuration and excluded from `repr`/public serialization.
- B14 execution clients contain no provider key and do not forward arbitrary Provider credentials.
- Tool authorization contains identifiers/scopes/approval markers only, never credential values.
- Tool handler and execution transport exception text is normalized rather than exposed.
- Context/evidence diagnostics expose bounded IDs/reasons/counts, not private corpus bytes or hidden system prompts.
- Tests use mock/in-process handlers and transports; no live provider credential is required.

## Current integration status

Current main contains accepted Core primitives for:

- shared contracts and read-only Web Runtime;
- B14 execution transport;
- completed, streaming and bounded multimodal execution facades;
- search decision, search preparation, source quality/relevance and grounding/research runtime;
- context permission and knowledge-boundary filtering;
- permission-gated tool runtime and registries;
- memory/RAG contracts and bounded context assembly;
- evidence graph, verification, citation and claim assessment;
- skill registry/activation/runtime semantics;
- agent planning/approval/delegation/recovery/events;
- orchestration runner/events and adapter conformance.

Known consumer/projection boundaries:

- Padiem Chat and Living Learning have accepted consumer evidence for selected Core execution/grounding paths.
- Padiem AI Engine exposes product-neutral completed/streaming/orchestration service boundaries where its contract manifest marks them available.
- Engine projections explicitly marked deferred/unavailable are not made available merely because Core source exists.
- Production/runtime activation remains separately authorized per product/service.

## Still deliberately deferred or separately gated

- model-native tool/function-call protocol;
- write-capable browser actions;
- multimodal streaming;
- multiple-image, audio or video expansion;
- product-specific tool adapters;
- product-specific persistence/storage adapters;
- B61 StoryMemory locator ordering, annotation schema, reading progress and spoiler UX;
- B62 product UI, conversation/history/project/file presentation and model-mode UX;
- Engine projections marked deferred/unavailable in the Engine contract manifest;
- durable production idempotency adapter wiring where not yet injected at the real boundary;
- Shared Control Plane live entitlement/billing/payment enforcement where not separately frozen and activated;
- Provider/model selection for B62 LOW/MEDIUM/HIGH unless explicitly assigned through B14/product contract;
- remote/MCP tool registry;
- Production re-arm/deployment/secret activation.

Current B62 model-profile authority remains outside Core. Core may normalize product-supplied model policy, but B14/product contracts determine actual assigned model/provider routes.

Authorities: #1101, #1315, `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`, and earlier Core slice issues including #809, #811, #814, #819, #828, #835, #919, #924, #1068, #1172-#1177, #1198, #1212, #1308 and #1313.
