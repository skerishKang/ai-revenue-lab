# Padiem AI Capability Ownership Registry v1

```text
DOC_STATUS = CANONICAL_CAPABILITY_OWNERSHIP
OWNER = Padiem platform architecture
SCOPE = stable ownership of reusable AI capabilities
LAST_VERIFIED = 2026-09-08
```

This registry answers **who owns a capability**. It is intentionally not a live dashboard for deployment, Provider readiness, exact route IDs, open PRs or Production activation.

## Canonical ownership rule

```text
PRODUCTS OWN DOMAIN + UX.
IP-SIDECAR OWNS REUSABLE EMBEDDED SHELL/CONTEXT/EVENT PRIMITIVES.
IP-CORE OWNS REUSABLE AI SEMANTICS.
IP-ENGINE OWNS CROSS-RUNTIME SERVICE PROJECTION.
B14 OWNS PROVIDER/MODEL EXECUTION.
IP-CONTROL OWNS IDENTITY / TENANT / ENTITLEMENT / USAGE / AUDIT TRUTH.
```

## Required classification

Every new AI capability should be classified before implementation:

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

## Stable layer ownership

| Layer | Owns | Must not own |
|---|---|---|
| Product / Business | domain semantics, UX, product persistence, product adapters, product-local admission/presentation | generic AI runtime policy, generic Provider router |
| IP-SIDECAR | reusable embedded shell lifecycle, browser-safe bootstrap, host-context envelope, public-safe event projection, host adapter integration contract | product domain meaning, Core semantics, Engine service identity/transport, B14 routing/credentials |
| IP-ENGINE | trusted cross-runtime service/API projection of accepted Core semantics | competing Core policy engine, product UX, Provider routing |
| IP-CORE | reusable execution, grounding, permission, retrieval/memory, Evidence, Tool, Skill, Agent and orchestration semantics | product-domain schema/UI, Provider catalog/credentials |
| B14 Korean AI Platform | Provider/model registry, inference credentials, executable route validation/selection, Provider adapters and actual execution | product memory/domain state, Control Plane identity truth |
| IP-CONTROL | canonical identity/subject/tenant, entitlement, usage/credits/subscription/audit and neutral cross-product declarations | Provider/model execution, product conversation state |

## IP-CORE capability families

Generic reusable semantics belong to Core, including:

- completed/streaming/multimodal execution contracts;
- search decision, grounding, research and source-quality semantics;
- context permission and knowledge-boundary enforcement;
- retrieval, Memory/RAG authorization/ranking/receipt semantics;
- Evidence/citation/verification/claim assessment;
- Tool/Connector registry, authorization and lifecycle semantics;
- reusable Skill identity/version/activation semantics;
- reusable Agent planning, approval, delegation, recovery and event semantics;
- orchestration and execution-context semantics.

Products may provide bounded domain adapters and presentation but must not fork generic policy.

## IP-ENGINE ownership

IP-ENGINE owns cross-runtime projection: trusted caller identity, Service Binding/API transport, execute/stream/orchestration projection, wire normalization, capability manifests and truthful health reporting.

It does not select Providers/models and does not own browser/product UX.

## B14 ownership

B14 owns Provider/model execution authority:

- Provider/model catalog and registry;
- inference credentials and trusted binding references;
- executable route validation/selection;
- Provider adapters/upstream transport;
- completed/streaming/multimodal model execution;
- route metadata and execution-level retry/fallback policy where explicitly enabled.

Current Padiem product declarations are explicit:

```text
Padiem Plus = Laguna
Padiem Pro  = Nemotron
Padiem Max  = HOLD
USER_VISIBLE_AUTO = NO
SILENT_FALLBACK = NO
```

Exact IDs and executability are volatile and must be checked against current Control Plane declaration and B14 source.

## IP-CONTROL ownership

IP-CONTROL owns neutral cross-product authority such as canonical subject/tenant, entitlement/subscription/credit, usage and audit contracts plus accepted shared declarations. It is not a second Provider router.

## Product ownership locks

### B62 · Padiem Chat

Owns chat UX, conversations/history, Projects, attachments, Saved Outputs, TaskModes/profile presentation and product context adapters. Generic Tool/Skill/Agent/Memory/Evidence semantics and Provider routing remain outside B62.

### B54 · Padiem Claw

Owns task/run/repository/workspace/GitHub product semantics. Shared Agent/Tool/Skill/approval/recovery/orchestration semantics belong to IP-CORE; cross-runtime projection belongs to IP-ENGINE; model execution belongs to B14.

### B61 · StoryMemory

Owns reader UX, locator grammar/order, reading progress, knowledge ceiling, annotations and spoiler/no-future semantics. Generic retrieval/permission/context/evidence remains IP-CORE-owned.

### B53 · Padiem Sidecar

Owns the commercial embedded-AI product: packaging, onboarding, installation/customer journey and product-specific adapters. It is distinct from `IP-SIDECAR`.

```text
IP-SIDECAR SOURCE = packages/padiem-embedded-runtime/
SOURCE_PRESENT = YES
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
```

## Terminology and history

Historical documents may contain:

```text
P01                -> legacy shared Core identifier; current = IP-CORE
LOW/MEDIUM/HIGH    -> historical B62 profile terminology; not current route authority
b14/auto            -> historical/compatibility identifier; not ordinary Padiem Profile v1 route
```

The exact pre-unification 2026-09-01 registry remains immutable in Git history at:

```text
COMMIT = f9ff7f81602138daa674811b9650bb7ffc86cf97
PATH = docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md
```

`docs/history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md` is the stable historical pointer to that revision. The old point-in-time status inventory does not override this canonical ownership registry.

## Readiness rule

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

Operational state must be verified from current source, manifests and deployment evidence. This registry owns stable architecture boundaries, not volatile runtime truth.
