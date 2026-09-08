# Padiem AI Capability Ownership Registry v1

Authority issue: #1315  
Cross-axis contract authority: #1099  
Shared Core roadmap: #1101  
Audit base: `f9ff7f81602138daa674811b9650bb7ffc86cf97` (2026-09-01)

## 0. Purpose

This registry prevents B14, B61 StoryMemory, B62 Padiem Chat, Padiem AI Core and Padiem AI Engine from independently creating overlapping AI harnesses or policy engines.

It is an ownership index, not a replacement for product contracts, Core contracts, or the B14 router specification.

Canonical rule:

```text
PRODUCTS KNOW DOMAIN STATE.
PADIEM AI CORE KNOWS REUSABLE AI SEMANTICS.
PADIEM AI ENGINE EXPOSES THOSE SEMANTICS ACROSS RUNTIMES.
B14 KNOWS MODEL/PROVIDER EXECUTION.
```

Every future AI/harness issue or PR should classify the capability before implementation:

```text
REUSE_CORE
EXTEND_CORE
PRODUCT_ADAPTER
B14_EXECUTION
ENGINE_TRANSPORT
DO_NOT_SHARE
```

## 1. Evidence and audit boundary

The inventory uses the current public GitHub authority as follows:

- `packages/padiem-ai-core/**`: source inspection on the audit base.
- `apps/padiem-ai-engine/**`: source/contract-manifest inspection on the audit base.
- `apps/korean-ai-platform/**`: source/README inspection on the audit base.
- `apps/padiem-chat/**`: source/README inspection on the audit base.
- B61 StoryMemory: **issue/contract inventory only**. StoryMemory private HTML/JS/CSS/package bytes are intentionally not present in this public repository and are not inferred here.

`CODE_ON_MAIN` below means implementation is present in the audited Git main. It does **not** by itself mean a Production binding, secret, Provider, database, or product activation is live.

Status vocabulary:

```text
CODE_ON_MAIN       implementation exists on audited main
COMPAT_ADAPTER     product-local adapter exists but is not shared-semantic authority
IN_FLIGHT          implementation exists only in an open PR/active lane
PRODUCT_CONTRACT   product issue/contract defines ownership; public source may be absent
DEFERRED           explicitly not available/activated yet
NOT_OWNER          layer must not implement the generic capability
```

## 2. Canonical layer ownership

| Layer | Canonical ownership | Must not become |
| --- | --- | --- |
| **B61 StoryMemory** | reader/corpus domain state, canonical locators, annotations, reading progress, product knowledge-ceiling value, StoryMemory retrieval adapters, spoiler/co-reader UX | a generic context-policy engine, generic model router, generic evidence authority |
| **B62 Padiem Chat** | general chat UX, conversations, Projects, attachments, product modes/profiles, product context adapter, source/citation presentation, product admission/abuse controls | a generic Tool/Skill/Agent/Memory runtime or Provider router |
| **Padiem AI Core** | shared contracts, execution semantics, grounding, evidence, trust/relevance, permission, retrieval/memory semantics, Tool/Skill/Agent/Orchestration policy, bounded fail-closed behavior | a product UI/domain model or a second B14 Provider router |
| **Padiem AI Engine** | internal cross-runtime API/Service-Binding boundary that exposes Core execution/orchestration safely | a competing Core policy layer, product UX, public model router |
| **B14 Korean AI Platform** | inference Provider/model catalog, inference credentials, adapters, exact route selection, upstream model execution, route/fallback/retry/cost/availability authority | product memory/context semantics or product UX |
| **Shared Control Plane** | canonical identity, entitlement, usage/credit/audit where frozen separately | product chat/history or model routing |

### Credential clarification

The phrase `Provider credentials = B14` applies to **model/inference Provider credentials**.

Read-only web/tool connector credentials are a separate class. For example, the current Core `WebRuntimeConfig` contains server-only Firecrawl/Daum search credentials. These credentials belong to the trusted server/runtime hosting that Core capability; they do not transfer model-routing authority to Core and do not belong in browser/product state.

## 3. Shared capability registry — Padiem AI Core

| Capability | Owner | Class | Current anchor | Status | Product rule |
| --- | --- | --- | --- | --- | --- |
| `Evidence` normalized provenance contract | Core | REUSE_CORE | `contracts.py` | CODE_ON_MAIN | B61/B62 may project product display, not redefine evidence authority |
| `ToolSpec`, side-effect/approval/auth contract | Core | REUSE_CORE | `contracts.py`, `tool_runtime.py` | CODE_ON_MAIN | product tools adapt/register through trusted server state |
| `AgentProfile` / run/tool/usage metadata | Core | REUSE_CORE | `contracts.py` | CODE_ON_MAIN | no product-local generic agent profile schema |
| Web provider protocol | Core | REUSE_CORE | `web_runtime.py` | CODE_ON_MAIN | products choose/configure only through server-owned adapter/config |
| Firecrawl read-only web adapter | Core | REUSE_CORE | `web_runtime.py` | CODE_ON_MAIN | optional extractor/search provider, no browser secret |
| Daum web search adapter | Core | REUSE_CORE | `web_runtime.py`, #1302 | CODE_ON_MAIN / LIVE_HOLD | key/terms/Production activation remain separate gates |
| Public URL normalization / SSRF-adjacent literal-host policy | Core | REUSE_CORE | `web_runtime.py` | CODE_ON_MAIN | do not duplicate URL safety in B61/B62 as a competing authority |
| Search disposition / automatic search decision | Core | REUSE_CORE | `search_decision.py`; consumed by B62 `auto_grounding.py` | CODE_ON_MAIN | products may supply task context, not invent a second generic decision engine |
| Search grounding preparation | Core | REUSE_CORE | `search_preparation.py` | CODE_ON_MAIN | B62 adapter converts product state only |
| Source Trust + Relevance Gate | Core | REUSE_CORE | `source_quality.py`, #1308 | CODE_ON_MAIN | generic relevance/authority/community handling stays Core |
| Grounding context assembly | Core | REUSE_CORE | `grounding_runtime.py` | CODE_ON_MAIN | product copy/presentation stays outside Core |
| Search/fetch/deep-research evidence orchestration primitives | Core | REUSE_CORE | `GroundedResearchRuntime` | CODE_ON_MAIN | product-local planner/presentation may adapt but not add generic policy |
| Completed model execution facade | Core | REUSE_CORE | `execution_runtime.py` | CODE_ON_MAIN | B14 performs actual inference route/execution |
| Streaming model execution facade | Core | REUSE_CORE | `streaming_runtime.py` | CODE_ON_MAIN | Provider stream shape remains hidden below shared contract |
| Multimodal execution facade | Core | REUSE_CORE | `multimodal_execution_runtime.py` | CODE_ON_MAIN | product owns attachment UX/capability gate; B14 owns inference route |
| Execution state machine / context / idempotency semantics | Core | REUSE_CORE | `execution_state_machine.py`, `execution_context.py`, `contextual_execution.py` | CODE_ON_MAIN | Engine exposes; products do not fork state semantics |
| Retrieval contract / bounded retrieval context | Core | REUSE_CORE | `retrieval.py` | CODE_ON_MAIN | product/corpus adapter owns storage/domain locator meaning |
| Memory write authorization/policy | Core | REUSE_CORE | `memory.py` | CODE_ON_MAIN | Core policy != product persistence schema |
| Memory read authorization | Core | REUSE_CORE | `memory_read.py` | CODE_ON_MAIN | product DB/localStorage remains product/storage authority |
| Memory write receipt/idempotency | Core | REUSE_CORE | `memory_receipt.py` | CODE_ON_MAIN | no second receipt protocol in B61/B62 |
| Retrieval ranking / long-context memory assembly | Core | REUSE_CORE | `memory_context.py` | CODE_ON_MAIN | domain-specific retrieval features may provide candidates/metadata |
| Evidence graph / claim-evidence links | Core | REUSE_CORE | `evidence_graph.py` | CODE_ON_MAIN | product citations consume public projections |
| Evidence verification contract | Core | REUSE_CORE | `evidence_verification.py` | CODE_ON_MAIN | verification authority must not move into B62 presentation |
| Grounded citation projection | Core | REUSE_CORE | `evidence_citation.py` | CODE_ON_MAIN | B61 may additionally render internal canonical locators |
| Claim assessment | Core | REUSE_CORE | `evidence_assessment.py` | CODE_ON_MAIN | product UI may render disposition/copy |
| Tool registry | Core | REUSE_CORE | `tool_registry.py` | CODE_ON_MAIN | B62 tool list should converge to presentation metadata only |
| Connector registry | Core | REUSE_CORE | `connector_registry.py` | CODE_ON_MAIN | connector credentials/handlers remain trusted server-side |
| Tool resource policy / lifecycle | Core | REUSE_CORE | `tool_resource_policy.py`, `tool_lifecycle.py` | CODE_ON_MAIN | product cannot widen mandatory resource policy |
| Reusable Skill package/version/registry/activation | Core | REUSE_CORE | `skill_*` modules | CODE_ON_MAIN | B62 TaskModes are not Core Skills |
| Agent definition/profile compilation | Core | REUSE_CORE | `agent_definition.py`, `agent_profile_adapter.py` | CODE_ON_MAIN | products supply policy/input adapters only |
| Agent planning | Core | REUSE_CORE | `agent_planner.py` | CODE_ON_MAIN | no product-generic autonomous planner fork |
| Agent approval/pause/resume semantics | Core | REUSE_CORE | `agent_approval.py` | CODE_ON_MAIN | approval UI/copy remains product-owned |
| Agent delegation/recovery/events | Core | REUSE_CORE | `agent_delegation.py`, `agent_recovery.py`, `agent_events.py` | CODE_ON_MAIN | products cannot silently widen delegated authority |
| Plan-backed agent execution bridge | Core | REUSE_CORE | `agent_execution_bridge.py` | CODE_ON_MAIN | Engine may expose service boundary only |
| Orchestration runner/events | Core | REUSE_CORE | `orchestration.py`, `orchestration_events.py` | CODE_ON_MAIN | Engine service is transport/projection, not a competing semantic owner |
| Adapter conformance harness | Core | REUSE_CORE | `adapter_conformance.py` | CODE_ON_MAIN | every multi-product adapter should use shared conformance expectations |
| Context Permission + Knowledge Boundary | Core | EXTEND_CORE | #1313 / Draft PR #1314 | IN_FLIGHT | B61 computes domain ceiling; Core enforces generic allowed/filtered projection |

### Core documentation drift found by this audit

`packages/padiem-ai-core/README.md` still describes several capabilities such as agent execution and memory/RAG as deliberately deferred, while current main already contains the corresponding cumulative Core modules merged through #1256. The registry treats **current main code and accepted integration history as stronger inventory evidence than the stale paragraph**. README reconciliation should be a bounded follow-up; this registry does not rewrite feature behavior.

## 4. Padiem AI Engine registry

The audited Engine contract manifest exposes `/internal/v1/*` only and explicitly refuses Provider selection/public-browser ownership.

| Capability | Owner | Class | Current anchor | Status | Boundary |
| --- | --- | --- | --- | --- | --- |
| completed execution service | Engine | ENGINE_TRANSPORT | `/internal/v1/execute` | CODE_ON_MAIN | executes shared semantics; not product UX |
| streaming execution service | Engine | ENGINE_TRANSPORT | `/internal/v1/stream` | CODE_ON_MAIN | normalized internal stream boundary |
| health/internal contract surface | Engine | ENGINE_TRANSPORT | `/internal/v1/health` | CODE_ON_MAIN | no Provider secrets/inventory in public manifest |
| first-party service identity contract/enforcement | Engine | ENGINE_TRANSPORT | contract manifest + identity modules | CODE_ON_MAIN | trusted cross-runtime caller boundary |
| execution-context wire projection | Engine | ENGINE_TRANSPORT | `execution_context_wire.py` | CODE_ON_MAIN | projects Core execution context; does not redefine it |
| orchestration run | Engine | ENGINE_TRANSPORT | `/internal/v1/orchestrate` contract path | CODE_ON_MAIN | Core owns orchestration semantics |
| orchestration resume | Engine | ENGINE_TRANSPORT | `/internal/v1/orchestrate/resume` | CODE_ON_MAIN | transport/continuation boundary |
| orchestration cancel | Engine | ENGINE_TRANSPORT | `/internal/v1/orchestrate/cancel` | CODE_ON_MAIN | transport/continuation boundary |
| approval continuation projection | Engine | ENGINE_TRANSPORT | contract manifest feature | DEFERRED | do not claim active merely because supporting code exists |
| Tool Runtime projection | Engine | ENGINE_TRANSPORT | contract manifest feature | DEFERRED | Core remains owner |
| Skill Runtime projection | Engine | ENGINE_TRANSPORT | contract manifest feature | DEFERRED | Core remains owner |
| Agent Runtime projection | Engine | ENGINE_TRANSPORT | contract manifest feature | DEFERRED | Core remains owner |
| Memory/RAG projection | Engine | ENGINE_TRANSPORT | contract manifest feature | DEFERRED | Core semantics + product/storage adapter remain separate |
| public browser API | Engine | NOT_OWNER | contract manifest | UNAVAILABLE | products call through approved same-origin/server adapter |
| Provider selection | Engine | NOT_OWNER | contract manifest | UNAVAILABLE | B14 authority |

## 5. B14 Korean AI Platform registry

| Capability | Owner | Class | Current anchor | Status | Boundary |
| --- | --- | --- | --- | --- | --- |
| inference Provider registry/catalog | B14 | B14_EXECUTION | `apps/korean-ai-platform/app/pilot/catalog.py`, README | CODE_ON_MAIN | Core may carry normalized requested policy, not own catalog truth |
| inference Provider credentials / BYOK handling | B14 | B14_EXECUTION | B14 gateway/config contracts | CODE_ON_MAIN | never browser-exposed through B61/B62/Core contracts |
| Provider adapter/upstream transport | B14 | B14_EXECUTION | `gateway.py`, `openrouter.py`, related pilot modules | CODE_ON_MAIN | no direct Provider fallback from Engine/products |
| exact model/provider routing | B14 | B14_EXECUTION | B14 routing/gateway contracts | CODE_ON_MAIN | B62 may request an approved model id; B14 remains execution authority |
| route/fallback/retry/cost/availability policy | B14 | B14_EXECUTION | B14 routing layer | CODE_ON_MAIN / policy-specific | products must not fork generic Provider routing |
| completed model invocation | B14 | B14_EXECUTION | chat completion gateway | CODE_ON_MAIN | Core normalizes request/result around it |
| model streaming execution | B14 | B14_EXECUTION | `auto_stream_gateway.py` and stream contracts | CODE_ON_MAIN | Engine/Core consume normalized stream boundary |
| low-level multimodal/provider contract | B14 | B14_EXECUTION | `multimodal_contract.py` + gateway | CODE_ON_MAIN | Core higher-level multimodal facade validates shared request semantics |
| route metadata returned upward | B14 | B14_EXECUTION | route metadata contract | CODE_ON_MAIN | only allowlisted safe metadata should cross Core boundary |
| B14 Korean-first workspace UI | B14 | DO_NOT_SHARE | B14 product workspace | CODE_ON_MAIN | B14's own product UX, not shared Core UI |

## 6. B62 Padiem Chat registry

B62's current README already declares that reusable Skill/Tool/Evidence/Grounding semantics belong outside the product boundary. The code audit confirms substantial adapter reuse of Core.

| Capability | Owner | Class | Current anchor | Status | Boundary / promotion decision |
| --- | --- | --- | --- | --- | --- |
| chat composer/sidebar/conversation UI | B62 | DO_NOT_SHARE | `apps/padiem-chat/static/**` | CODE_ON_MAIN | product UX |
| conversation/history persistence | B62 | PRODUCT_ADAPTER | B62 auth/history/store routes | CODE_ON_MAIN | product data, not Core long-term memory semantics |
| Projects/project files/instructions | B62 | PRODUCT_ADAPTER | B62 project modules | CODE_ON_MAIN | product storage/context source; Core may consume bounded normalized context |
| Saved Outputs/copy/download | B62 | DO_NOT_SHARE | B62 product modules/UI | CODE_ON_MAIN | library UX, explicitly not automatic model memory |
| attachment UX and extraction | B62 | PRODUCT_ADAPTER | `attachments.py`, `binary_documents.py`, OOXML/document modules | CODE_ON_MAIN | product validates/extracts; model-execution semantics remain Core/B14 |
| product TaskModes | B62 | PRODUCT_ADAPTER | `task_modes.py` / product mode catalog | CODE_ON_MAIN | not reusable Core Skills |
| user-facing chat modes/profiles | B62 | PRODUCT_ADAPTER | `chat_modes.py`, `model_policy.py` | CODE_ON_MAIN | presentation/product eligibility only |
| current MEDIUM -> `poolside/laguna-s-2.1` assignment | B62 consumer policy + B14 execution | PRODUCT_ADAPTER | `model_policy.py`, #1295 | CODE_ON_MAIN | temporary/current approved exact request; **does not grant B62 Provider registry/routing authority** |
| LOW/HIGH profile placeholders | B62 | PRODUCT_ADAPTER | `model_policy.py` | CODE_ON_MAIN / UNASSIGNED | must fail closed until explicitly assigned |
| automatic search enablement/presentation | B62 | PRODUCT_ADAPTER | `auto_grounding.py` | COMPAT_ADAPTER | calls Core `decide_search` + search preparation; no second decision semantics |
| web search/fetch/deep-research product service | B62 | PRODUCT_ADAPTER | `grounding.py` | COMPAT_ADAPTER | uses Core `GroundedResearchRuntime`; no new generic evidence/recovery policy may land here |
| deep-research planner/synthesizer prompts | B62 currently | PRODUCT_ADAPTER | `grounding.py` | COMPAT_ADAPTER | product prompt/presentation allowed; generic orchestration evolution belongs Core |
| tool labels/icons/visibility | B62 | PRODUCT_ADAPTER | tool presentation layer | CODE_ON_MAIN | Core owns ToolSpec/runtime/authorization |
| evidence/source UI projection | B62 | PRODUCT_ADAPTER | grounding/public response | COMPAT_ADAPTER | Core owns Evidence/verification/citation semantics |
| product auth/session continuity | B62 + Control Plane bridge | PRODUCT_ADAPTER | B62 auth modules, #1228 | CODE_ON_MAIN | canonical cross-product identity belongs Control Plane |
| product admission/abuse quota | B62 | PRODUCT_ADAPTER | `dispatch_quota.py` | CODE_ON_MAIN | product release safety; canonical metering/credit remains Control Plane |
| themes/locale/accessibility/mobile | B62 | DO_NOT_SHARE | static product surface | CODE_ON_MAIN | no Core ownership |

## 7. B61 StoryMemory registry

**Important:** this section is derived from public GitHub issue contracts (#1129, #1261, #1284, #1305, #1307 and related accepted B61 issues). It does not claim to inspect the private StoryMemory package bytes.

| Capability | Owner | Class | Authority/status | Boundary / promotion decision |
| --- | --- | --- | --- | --- |
| StoryMemory reader state extraction | B61 | PRODUCT_ADAPTER | #1307 PRODUCT_CONTRACT | current work/page/unit/visible range is domain state |
| canonical locator identity/order | B61 | PRODUCT_ADAPTER | #1307/#1305 | Core must not learn Bible/classic locator semantics |
| selected text -> canonical locator projection | B61 | PRODUCT_ADAPTER | #1307 | product mapping; normalized output may feed Core |
| annotation schema/storage | B61 | DO_NOT_SHARE | accepted `storymemory.annotations.v1`, #1292/#1307 | localStorage/product data, not Core memory storage |
| bookmark/highlight/underline/memo state | B61 | PRODUCT_ADAPTER | #1292/#1307 | may become bounded context candidates; Core does not own UI/storage |
| reading progress / furthest-read locator | B61 | PRODUCT_ADAPTER | #1305 | computes domain knowledge ceiling input |
| `knowledge_ceiling_locator` value | B61 | PRODUCT_ADAPTER | #1305 | B61 computes; Core #1313/#1314 enforces generic boundary |
| HARD_NO_FUTURE StoryMemory policy | B61 | PRODUCT_ADAPTER | #1305 | StoryMemory product specialization; product may only narrow Core policy |
| spoiler/co-reader refusal copy | B61 | DO_NOT_SHARE | #1305 | user-facing product copy stays local |
| ReaderContext / AnnotationContext / AIContextPacket | B61 | PRODUCT_ADAPTER | #1307 OPEN | domain packet foundation; must not become second generic ContextPolicy engine |
| current-page/source-grounded question adapter | B61 | PRODUCT_ADAPTER | #1129 OPEN | should call Engine/Core; no direct Provider call |
| same-origin StoryMemory -> Engine adapter | B61 | ENGINE_TRANSPORT consumer | #1129 | fail closed if Engine binding absent; no Provider fallback |
| corpus locator search | B61 | PRODUCT_ADAPTER | #1284 planning | domain retrieval/index semantics |
| corpus book/chapter/unit search | B61 | PRODUCT_ADAPTER | #1284 planning | domain navigation semantics |
| static lexical keyword search | B61 | PRODUCT_ADAPTER | #1284 planning | product/corpus retrieval provider candidate |
| annotation search | B61 | PRODUCT_ADAPTER | #1284 planning | product data retrieval |
| retrieval context packet | B61 adapter + Core retrieval | PRODUCT_ADAPTER/REUSE_CORE | #1284 downstream | B61 supplies locator/text/provenance; Core owns generic retrieval/context policy |
| future vector/embedding backend | TBD storage adapter, Core contract consumer | PRODUCT_ADAPTER/REUSE_CORE | #1284 DEFERRED | do not put vector-store choice into Core contract by default |
| internal locator citation display | B61 | PRODUCT_ADAPTER | #1261/#1284 | generic evidence citation can come from Core; StoryMemory locator presentation stays B61 |
| corpus/private source bytes | B61 | DO_NOT_SHARE | #673 private-source boundary | never imported into Core/public repo merely for reuse |

## 8. Overlap reconciliation — current hotspots

### 8.1 B61 Context Harness vs Core Context Permission

```text
B61 #1307/#1305
  computes domain facts:
  reader state / locator / annotations / furthest-read / ceiling
        ↓ trusted adapter
Core #1313 / PR #1314
  applies generic allowed/filtered context projection
  prevents user/model from widening trusted boundary
        ↓
model invocation
```

Decision:

```text
B61_CONTEXT_HARNESS = KEEP
GENERIC_CONTEXT_PERMISSION_IN_B61 = PROHIBITED
CORE_STORYMEMORY_LOCATOR_SEMANTICS = PROHIBITED
```

### 8.2 B62 automatic web grounding vs Core search/grounding

Current B62 `auto_grounding.py` already imports Core `SearchDecision`, `decide_search` and `prepare_search_grounding`.

Decision:

```text
B62 = task/product adapter + enablement + Korean product errors/presentation
Core = search decision + evidence selection + grounding semantics
```

No new generic search-decision rules should be added only to B62.

### 8.3 B62 deep research vs Core orchestration

B62 currently carries planner/synthesizer product prompts while Core performs bounded research/evidence orchestration.

Decision:

```text
CURRENT B62 ADAPTER = ACCEPTED COMPATIBILITY
NEW GENERIC RECOVERY / APPROVAL / TOOL / AGENT / EVIDENCE SEMANTICS = CORE ONLY
FUTURE MIGRATION = thin B62 presentation over stable Core/Engine orchestration when justified
```

No purity refactor is required solely to move working prompts.

### 8.4 B62 exact Laguna mapping vs B14 router ownership

Current B62 rollout maps MEDIUM exactly to `poolside/laguna-s-2.1` and deliberately avoids unconstrained `b14/auto`.

This is an approved **consumer policy / requested model assignment**, not a second Provider router.

B62 may state:

```text
this product profile is allowed to request model X
```

B62 must not own:

```text
Provider endpoint
Provider credential
Provider registry
Provider availability/cost truth
cross-provider retry/fallback
upstream execution transport
```

Those remain B14.

### 8.5 Product persistence vs Core Memory/RAG

B61 annotations/progress and B62 conversations/Projects/Saved Outputs are product-owned persistence.

Core Memory/RAG owns reusable semantics such as retrieval/write authorization, provenance, ranking/context assembly and receipts. Core does not absorb product tables/localStorage merely because they may later supply memory candidates.

```text
PRODUCT STORAGE != CORE MEMORY POLICY
```

### 8.6 Engine orchestration vs Core orchestration

Engine exposes internal service endpoints and first-party identity/wire rules. Core owns orchestration semantics.

```text
Core = what the orchestration means
Engine = how another runtime safely invokes it
```

The Engine contract manifest already marks `provider_selection` unavailable and several tool/skill/agent/memory projections deferred, preventing accidental authority expansion.

## 9. Promotion decision procedure

Before implementation, use this order:

```text
1. REUSE_AUDIT
   Search current Core/B14/Engine/product contracts and active PRs.

2. DOMAIN TEST
   Does correctness require product-specific meaning/state?
   YES -> PRODUCT_ADAPTER or DO_NOT_SHARE.

3. EXECUTION TEST
   Is it inference Provider/model routing, credentials, fallback/retry or upstream execution?
   YES -> B14_EXECUTION.

4. TRANSPORT TEST
   Is it only cross-runtime API/service binding/serialization/identity enforcement?
   YES -> ENGINE_TRANSPORT.

5. CORE TEST
   Is it reusable AI semantics, or a product-neutral safety/correctness invariant?
   YES -> REUSE_CORE if present, otherwise EXTEND_CORE.

6. RULE OF TWO
   If a second product needs the same generic semantics, do not copy them into the second product; promote/freeze in Core first.

7. SAFETY EXCEPTION
   permission/trust/provenance/fail-closed/security invariants are Core-first immediately when product-neutral.
```

## 10. Required issue/PR preflight fields

Every future AI/harness issue/PR in these lanes should state:

```text
CAPABILITY_OWNER = B61 | B62 | CORE | ENGINE | B14 | CONTROL_PLANE | OTHER
CAPABILITY_CLASS = REUSE_CORE | EXTEND_CORE | PRODUCT_ADAPTER | B14_EXECUTION | ENGINE_TRANSPORT | DO_NOT_SHARE
REUSE_AUDIT = <issues/files/contracts checked>
OVERLAP_WITH = <issue/PR/file list or NONE>
CORE_PROMOTION_REQUIRED = YES | NO
CONTRACT_IMPACT = NONE | BACKWARD_COMPATIBLE | BREAKING
PRODUCT_SPECIFIC_SEMANTICS_IN_CORE = 0
GENERIC_CORE_DUPLICATION_IN_PRODUCT = 0
```

Implementation should not begin when `REUSE_AUDIT` is absent for a new AI/harness capability.

## 11. Conformance model

Shared semantics require two different tests:

```text
Core contract/unit regression
        +
Product adapter conformance
        +
Cross-runtime Engine contract test when Engine is used
        +
B14 route/execution contract test when model execution is used
```

A product test must prove that its adapter cannot widen trusted Core policy. Core tests must prove that Core contains no B61/B62 domain semantics.

## 12. Immediate decisions from this inventory

```text
#1308 Source Trust + Relevance          -> CORE authority, DONE
#1313 Context Permission               -> CORE authority, implementation IN_FLIGHT via Draft #1314
#1307 B61 Context Harness              -> B61 PRODUCT_ADAPTER, continue without Core duplication
#1305 B61 Knowledge Ceiling            -> B61 computes domain ceiling; Core enforces generic boundary
#1284 B61 Retrieval                    -> B61 corpus adapter + existing Core retrieval contract; no second generic RAG policy
#1298/#1302 B62 grounded search        -> B62 product adapter/presentation + Core web/search/grounding semantics
B62 exact Laguna assignment            -> current product consumer policy only; B14 execution authority preserved
Engine tool/skill/agent/memory projection -> remain DEFERRED until separately activated
```

No immediate refactor is authorized solely for architectural cleanliness. Working compatibility adapters remain until a concrete shared seam or defect justifies migration.

## 13. Registry maintenance rule

Update this registry when any of the following occurs:

```text
- a capability changes canonical owner;
- a second product begins consuming a previously product-local generic AI semantic;
- a Core capability becomes stable/removed/replaced;
- an Engine feature moves between DEFERRED / AVAILABLE / UNAVAILABLE;
- B14 execution authority changes materially;
- a product adapter is promoted to a shared contract;
- a new overlap exception is accepted.
```

Do not use this registry to silently authorize Production deployment, secrets, Provider activation, B61 private-source publication, or breaking contract migration.

## 14. Acceptance snapshot

```text
AI_CAPABILITY_INVENTORY = COMPLETE_FOR_AUDIT_BASE
B14_EXECUTION_AUTHORITY = PRESERVED
CORE_SHARED_INTELLIGENCE_AUTHORITY = PRESERVED
ENGINE_TRANSPORT_AUTHORITY = PRESERVED
B61_DOMAIN_AUTHORITY = PRESERVED
B62_PRODUCT_AUTHORITY = PRESERVED
MODEL_PROVIDER_CREDENTIAL_CLASS = B14
WEB_TOOL_CREDENTIAL_CLASS = TRUSTED_CORE_TOOL_RUNTIME_HOST
RULE_OF_TWO = ACTIVE
SAFETY_CORE_FIRST_EXCEPTION = ACTIVE
CORE_NO_BACKFLOW = ACTIVE
GENERIC_DUPLICATION_ACROSS_PRODUCTS = PROHIBITED
B61_PRIVATE_SOURCE_PUBLISHED = NO
PRODUCTION_MUTATION = 0
SECRET_MUTATION = 0
```
