# Padiem / AI Revenue Lab Documentation

```text
DOC_STATUS = CANONICAL_ENTRYPOINT
OWNER = repository documentation governance
LAST_VERIFIED = 2026-09-08
```

`docs/` is the entrypoint for **current documentation authority**. Dated audits, issue-specific designs, phase documents and Git history remain evidence; file existence alone does not make them current architecture or runtime truth.

## Start here

1. `architecture/PADIEM_AI_VERTICAL_STACK.md` — canonical product-to-Provider topology
2. `architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` — stable capability ownership
3. `internal-platform/README.md` — Internal Platform overview
4. `internal-platform/INTERNAL_PLATFORM_REGISTRY.md` — IP-CORE / IP-ENGINE / IP-CONTROL / IP-SIDECAR identities
5. `internal-platform/AI_ADOPTION_PLAYBOOK.md` — reuse/extend/adapter classification
6. `product/AI_PRODUCT_CONSUMER_MATRIX.md` — product-to-platform relationships
7. `governance/DOCUMENTATION_AUTHORITY_MODEL.md` — document precedence/freshness
8. `governance/LEGACY_AI_TERMINOLOGY_MAP.md` — legacy terminology interpretation

Audit trail:

- `DOCUMENTATION_AUDIT_20260908.md`
- `DOCUMENTATION_RECONCILIATION_COMPLETION_20260908.md`

## Canonical AI topology

```text
Product / Business domain + UX
        |
        +--> optional IP-SIDECAR embedded shell/context/event primitives
        |
        v
IP-ENGINE   cross-runtime trusted service boundary
        |
        v
IP-CORE     reusable AI semantics/contracts/runtime
        |
        v
B14         Provider/model catalog, routing, credentials and execution
        |
        v
Provider / Model

IP-CONTROL = cross-cutting identity / tenant / entitlement / usage / audit
             + neutral cross-product declarations
```

Same-runtime consumers may use IP-CORE directly only when architecture explicitly permits it. Products must not create a second generic Provider/model router or shared AI policy engine.

## Current component and product authority

```text
packages/padiem-ai-core/README.md           -> IP-CORE
apps/padiem-ai-engine/README.md             -> IP-ENGINE
packages/padiem-control-plane/README.md     -> IP-CONTROL
packages/padiem-embedded-runtime/README.md  -> IP-SIDECAR S2 source contract
docs/internal-platform/sidecar/README.md     -> IP-SIDECAR ownership/readiness
docs/products/padiem-sidecar/README.md       -> B53 Padiem Sidecar commercial product authority
apps/korean-ai-platform/README.md            -> B14 execution platform
apps/padiem-chat/README.md                   -> B62 Padiem Chat
apps/korean-ai-code-agent/README.md          -> B54 Padiem Claw
```

## Product boundary locks

- **B62 Padiem Chat** owns chat UX, conversations, Projects, attachments, Saved Outputs and product modes. Generic Tool/Skill/Agent/Memory/Evidence semantics remain IP-CORE-owned.
- **B54 Padiem Claw** owns task/run/repository/workspace/GitHub product flow. `P01` is historical terminology for the shared Core lineage; current canonical identity is `IP-CORE`.
- **B61 StoryMemory** owns reader/domain semantics including locator grammar, progress, knowledge ceiling and spoiler/no-future behavior. Generic retrieval/permission/evidence remains IP-CORE-owned.
- **B53 Padiem Sidecar** is the commercial product whose product charter, requirements, architecture, operations, security and commercialization documents live under `docs/products/padiem-sidecar/`.
- **IP-SIDECAR** is the reusable embedded runtime layer consumed by B53 and future approved hosts. B53 and IP-SIDECAR are distinct authorities.
- **B14 Korean AI Platform** owns Provider/model registry, inference credentials, executable route validation/selection and actual model execution.

## IP-SIDECAR current state

```text
SOURCE = packages/padiem-embedded-runtime/
SOURCE_PRESENT = YES
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
```

S2 source presence proves only the bounded embedded runtime contract, not live Engine or Provider connectivity.

## Padiem tier terminology

Current product-level documentation uses:

```text
Padiem Plus = Laguna
Padiem Pro  = Nemotron
Padiem Max  = HOLD
USER_VISIBLE_AUTO = NO
SILENT_FALLBACK = NO
```

Exact route IDs and executability must be verified from current Control Plane declaration and B14 catalog/source. Historical LOW/MEDIUM/HIGH wording is not current route authority.

## Documentation authority order

When documents disagree:

```text
1. current merged source / executable contract / manifest for volatile runtime facts
2. canonical architecture + registries
3. current component/product README and product contract
4. accepted ADR
5. dated audit/evidence record
6. historical issue/PR discussion
```

Business numbering remains governed by `portfolio/BUSINESS_REGISTRY.md`.

## Historical evidence

Pre-unification evidence is retained in two forms:

```text
history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md
  -> immutable pointer to the exact registry at audit commit f9ff7f81602138daa674811b9650bb7ffc86cf97

history/2026-09-01/PADIEM_AI_CORE_README.snapshot.md
history/2026-09-02/PADIEM_CLAW_README.snapshot.md
  -> preserved historical document snapshots
```

Historical evidence may contain stale identifiers and runtime status. It does not override current authority.

## Readiness rule

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

A class, route, README, UI control or passing unit test does not by itself prove a live Provider, connector, secret, database, service binding or Production deployment.
