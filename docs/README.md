# Padiem / AI Revenue Lab Documentation

```text
DOC_STATUS = CANONICAL_ENTRYPOINT
OWNER = repository documentation governance
LAST_VERIFIED = 2026-09-08
```

`docs/` is the entrypoint for finding **current documentation authority**. This repository also contains dated audits, phase documents, issue-specific designs and historical snapshots; file existence alone does not make every document equally current.

## 1. Read these first

For the Padiem AI vertical stack, use this order:

1. [`architecture/PADIEM_AI_VERTICAL_STACK.md`](architecture/PADIEM_AI_VERTICAL_STACK.md) — canonical product-to-Provider architecture
2. [`architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`](architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md) — stable capability ownership
3. [`internal-platform/README.md`](internal-platform/README.md) — IP-CORE / IP-ENGINE / IP-CONTROL / IP-SIDECAR relationship
4. [`internal-platform/INTERNAL_PLATFORM_REGISTRY.md`](internal-platform/INTERNAL_PLATFORM_REGISTRY.md) — Internal Platform identity registry
5. [`internal-platform/AI_ADOPTION_PLAYBOOK.md`](internal-platform/AI_ADOPTION_PLAYBOOK.md) — reuse/extend/adapter classification for new AI work
6. [`product/AI_PRODUCT_CONSUMER_MATRIX.md`](product/AI_PRODUCT_CONSUMER_MATRIX.md) — Chat, Claw, StoryMemory, Sidecar and other AI consumers
7. [`governance/DOCUMENTATION_AUTHORITY_MODEL.md`](governance/DOCUMENTATION_AUTHORITY_MODEL.md) — document precedence and freshness rules
8. [`governance/LEGACY_AI_TERMINOLOGY_MAP.md`](governance/LEGACY_AI_TERMINOLOGY_MAP.md) — P01, LOW/MEDIUM/HIGH, b14/auto and other historical-term interpretation

Audit trail:

- [`DOCUMENTATION_AUDIT_20260908.md`](DOCUMENTATION_AUDIT_20260908.md) — initial drift findings
- [`DOCUMENTATION_RECONCILIATION_COMPLETION_20260908.md`](DOCUMENTATION_RECONCILIATION_COMPLETION_20260908.md) — reconciliation completion record

## 2. Canonical Padiem AI topology

```text
Product / Business domain + UX
        │
        ├─ optional IP-SIDECAR embedded presentation/runtime
        │
        ▼
IP-ENGINE · cross-runtime trusted service boundary
        │
        ▼
IP-CORE · reusable AI semantics/contracts/runtime
        │
        ▼
B14 · Provider/model catalog, routing, credentials and execution
        │
        ▼
Provider / Model

IP-CONTROL = cross-cutting identity / tenant / entitlement / usage / audit
             + neutral cross-product declarations
```

Same-runtime consumers may use IP-CORE directly only when explicitly accepted by architecture. Products must not recreate a generic Provider/model router or competing shared AI policy engine.

## 3. Current component/product documentation

```text
packages/padiem-ai-core/README.md          -> IP-CORE
apps/padiem-ai-engine/README.md            -> IP-ENGINE
packages/padiem-control-plane/README.md    -> IP-CONTROL
apps/korean-ai-platform/README.md           -> B14 Router/Provider execution
apps/padiem-chat/README.md                  -> B62 Padiem Chat
apps/korean-ai-code-agent/README.md         -> B54 Padiem Claw
docs/internal-platform/sidecar/README.md    -> IP-SIDECAR proposed runtime
```

Product READMEs describe product behavior and integration. They do not override central platform ownership.

## 4. Product ownership boundaries

### B62 · Padiem Chat

Owns general chat UX, conversations/history, Projects, attachments, Saved Outputs, TaskModes/profile presentation and product context adapters. Generic Tool/Skill/Agent/Memory/Evidence semantics belong to IP-CORE; cross-runtime projection belongs to IP-ENGINE; model execution belongs to B14.

### B54 · Padiem Claw

Owns task/run/repository/workspace/GitHub product flow. Reusable Agent/Tool/Skill/approval/recovery/orchestration semantics belong to IP-CORE. `P01` is historical terminology; current identifier is `IP-CORE`.

### B61 · StoryMemory / Bible-classic-work domain

Owns reader UX, locator grammar/order, reading progress, knowledge ceiling, annotations and spoiler/no-future semantics. Generic retrieval permission/context/evidence belongs to IP-CORE.

### B53 · Padiem Sidecar vs IP-SIDECAR

```text
B53 Padiem Sidecar = commercial product / packaging / onboarding / customer journey
IP-SIDECAR         = proposed reusable embedded presentation/runtime layer
```

These identities must not be collapsed.

### B14 · Korean AI Platform

B14 is the general AI Router Platform and owns Provider/model registry, inference credentials, executable route validation/selection and actual model execution. The Router is an internal B14 capability, not a separate Business or Internal Platform ID.

## 5. Current Padiem tier terminology

Current product-level documentation uses:

```text
Padiem Plus = Laguna
Padiem Pro  = Nemotron
Padiem Max  = HOLD
USER_VISIBLE_AUTO = NO
SILENT_FALLBACK = NO
```

Exact current route IDs and executability are volatile and must be verified from:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
apps/korean-ai-platform/app/pilot/**
```

Historical LOW/MEDIUM/HIGH profile wording is not current route authority.

## 6. Documentation authority order

When documents disagree:

```text
1. current merged source / executable contract / manifest for volatile runtime facts
2. canonical architecture + registries
3. current component/product README and product contract
4. accepted ADR
5. dated audit/evidence snapshot
6. historical issue/PR discussion
```

Business numbering remains governed by `portfolio/BUSINESS_REGISTRY.md` where applicable.

## 7. Historical and evidence snapshots

Dated, issue-numbered, phase-specific or explicitly archived documents may preserve old terminology and old runtime state. They are evidence, not current authority.

Exact pre-unification snapshots preserved during the 2026-09-08 reconciliation include:

```text
history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md
history/2026-09-01/PADIEM_AI_CORE_README.snapshot.md
history/2026-09-02/PADIEM_CLAW_README.snapshot.md
```

Do not delete historical evidence merely because current terminology changed.

## 8. Readiness rule

Across Core, Engine, Control Plane, products and B14:

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

A class, route, README, UI control or passing unit test does not by itself prove a live Provider, connector, secret, database, service binding or Production deployment.

## 9. New document rule

New canonical documents should declare, when practical:

```text
DOC_STATUS = CANONICAL | CURRENT_COMPONENT | CURRENT_PRODUCT | RUNBOOK | ADR | EVIDENCE_SNAPSHOT | HISTORICAL
OWNER = <platform/product/domain>
SCOPE = <what this document owns>
LAST_VERIFIED = YYYY-MM-DD
SUPERSEDES = <path or NONE>
```

Stable ownership belongs in canonical architecture/registries. Volatile deployment/provider state belongs in source, manifests, runbooks or dated evidence rather than being copied into many READMEs.
