# Padiem AI Capability Ownership Registry v1

```text
DOC_STATUS = CANONICAL_CAPABILITY_OWNERSHIP
OWNER = Padiem platform architecture
SCOPE = stable ownership of reusable AI capabilities across products and shared platform layers
LAST_VERIFIED = 2026-09-08
SUPERSEDES = 2026-09-01 runtime-status-oriented registry snapshot
```

This registry answers **who owns a capability**. It intentionally does not act as a live dashboard for exact runtime availability, deployment, Provider readiness or open-PR status.

Canonical architecture:

```text
PRODUCTS OWN DOMAIN + UX.
IP-CORE OWNS REUSABLE AI SEMANTICS.
IP-ENGINE OWNS CROSS-RUNTIME SERVICE PROJECTION.
B14 OWNS PROVIDER/MODEL EXECUTION.
IP-CONTROL OWNS IDENTITY / TENANT / ENTITLEMENT / USAGE / AUDIT TRUTH.
IP-SIDECAR OWNS REUSABLE EMBEDDED PRESENTATION/RUNTIME PRIMITIVES WHEN FORMALLY ACTIVATED.
```

Related authority:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md`

## 1. Required classification

Every new AI capability or issue must be classified before implementation:

```text
REUSE_CORE
EXTEND_CORE
ENGINE_TRANSPORT
B14_EXECUTION
CONTROL_PLANE
IP_SIDECAR
PRODUCT_ADAPTER
DO_NOT_SHARE
```

If two layers appear to own the same generic policy, implementation stops until ownership is resolved.

## 2. Stable layer ownership

| Layer | Canonical identity | Owns | Must not become |
|---|---|---|---|
| Product / Business | B61/B62/B54/B53/etc. | domain semantics, UX, product persistence, product adapter, product-local admission/presentation | generic AI runtime policy, generic Provider router |
| Embedded runtime candidate | IP-SIDECAR | reusable drawer/panel/shell, host bridge, browser-safe lifecycle/evidence/action presentation | product domain model, Core reasoning, Engine auth, B14 routing |
| Service boundary | IP-ENGINE | trusted cross-runtime API/service projection of accepted Core semantics | competing Core policy engine, product UX, Provider router |
| Shared semantics | IP-CORE | execution, grounding, permission, retrieval/memory, Evidence, Tool, Skill, Agent, orchestration semantics | product domain schema/UI, Provider catalog/credentials |
| Execution plane | B14 Korean AI Platform | Provider/model registry, inference credentials, executable route validation/selection, upstream execution, execution-level retry/fallback policy | product memory/domain state, product UX, Control Plane identity truth |
| Cross-cutting authority | IP-CONTROL | identity, canonical subject/tenant, entitlement, usage/credits/subscription/audit, neutral cross-product declarations | Provider/model execution, product conversation state |
| External | Provider / Model | upstream model capability | Padiem product policy |

## 3. IP-CORE capability families

The following reusable capability families are IP-CORE-owned when generic across products:

| Capability family | Ownership rule |
|---|---|
| Execution contracts/runtime | Core normalizes product-neutral request/result/context semantics; B14 executes models |
| Streaming/multimodal facade | Core owns normalized shared semantics; product owns attachment/presentation policy; B14 owns Provider execution |
| Search/grounding/research | Core owns generic decision/preparation/evidence assembly; product owns task/domain context and presentation |
| Context permission / knowledge boundary | Core enforces generic allowed/filtered semantics; product computes/narrows domain-specific boundary values |
| Retrieval / Memory / RAG | Core owns generic authorization, receipt, ranking and context semantics; product/storage adapter owns persistence and domain locators |
| Evidence / citation / verification | Core owns generic evidence graph, verification and claim semantics; product owns rendering/domain citations |
| Tool / Connector | Core owns generic specs, authorization, registry/lifecycle semantics; product supplies bounded adapters/handlers |
| Skill | Core owns reusable Skill identity/version/activation/runtime semantics; product presets such as B62 TaskModes remain product-owned |
| Agent | Core owns reusable planning, profile, approval, delegation, recovery and events |
| Orchestration | Core owns reusable orchestration semantics/events; Engine projects accepted cross-runtime service contracts |
| Execution context | Core owns trace/timeout/cancellation/idempotency semantics; durable adapters remain separately composed |

Runtime availability of an individual module must be verified from current source, manifests and product composition rather than inferred from this registry.

## 4. IP-ENGINE capability ownership

IP-ENGINE owns cross-runtime projection only. Typical responsibilities include:

- trusted caller/service identity boundary;
- completed/streaming execution service projection;
- orchestration run/resume/cancel projection where the manifest marks it available;
- wire projection of Core execution context and events;
- truthful health/contract-manifest reporting.

IP-ENGINE must not select Providers/models, own browser/public product UX, or create a second semantic policy layer.

## 5. B14 capability ownership

B14 owns:

- Provider/model catalog and registry;
- inference Provider credentials and trusted binding references;
- executable route validation and selection;
- Provider adapters/upstream transport;
- actual completed/streaming/multimodal model execution;
- route metadata and execution-level availability/cost/latency observations;
- versioned generic routing/fallback/retry capability where explicitly enabled.

Current Padiem Routing Profile v1 is explicit-route policy, not a permanent ban on future B14 generic autorouting.

Current shared product declaration is:

```text
Padiem Plus = Laguna
Padiem Pro  = Nemotron
Padiem Max  = HOLD
USER_VISIBLE_AUTO = NO
SILENT_FALLBACK = NO
```

Exact route IDs and executability are verified from current Control Plane declaration + B14 catalog/source, not from historical issue text.

## 6. IP-CONTROL capability ownership

IP-CONTROL owns neutral cross-product authority such as:

- canonical subject/identity mapping;
- tenant/account authority;
- entitlement/subscription/credit/usage/audit truth;
- neutral shared product declarations such as the Padiem tier mapping.

It does not perform model execution and is not a second Provider router.

## 7. Product ownership locks

### B62 · Padiem Chat

Owns general chat UX, conversations/history, Projects, attachments, Saved Outputs, TaskModes/profile presentation and product context adapters. It must not duplicate generic Tool/Skill/Agent/Memory/Evidence semantics or Provider routing.

### B54 · Padiem Claw

Owns task/run/repository/workspace/GitHub product semantics. It consumes IP-CORE Agent/Tool/Skill/approval/recovery/orchestration semantics, IP-ENGINE cross-runtime projection and B14 execution.

Legacy `P01` references mean the former shared-Core identifier; current canonical name is `IP-CORE`.

### B61 · StoryMemory / Bible-classic-work domain

Owns reader UX, locator grammar/order, reading progress, knowledge ceiling, annotations and spoiler/no-future semantics. Generic retrieval/permission/context/evidence remains IP-CORE-owned.

### B53 · Padiem Sidecar

Owns the commercial embedded-AI product: packaging, onboarding, installation/customer journey and product-specific adapters. `B53 Padiem Sidecar` is not the same identity as `IP-SIDECAR`.

## 8. Terminology and history rule

Historical documents may contain:

```text
P01                    -> legacy shared Core identifier; current = IP-CORE
LOW / MEDIUM / HIGH     -> historical B62 profile terminology; not current Plus/Pro/Max route authority
b14/auto                -> historical/compatibility identifier; not ordinary Padiem Profile v1 route
phase-specific provider/model lists -> evidence for that phase only
```

See `docs/governance/LEGACY_AI_TERMINOLOGY_MAP.md`.

The exact pre-unification 2026-09-01 registry, including detailed runtime-status rows, is preserved at:

```text
docs/history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md
```

That snapshot remains valuable evidence but does not override this canonical stable-ownership registry.

## 9. Readiness rule

Across every layer:

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

Current operational status must be verified from current source, manifests, exact deployment evidence and product-specific runbooks. This registry owns architecture boundaries, not volatile deployment truth.
