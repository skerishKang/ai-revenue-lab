# Business 54 · Padiem Claw / Korean AI Code Agent

```text
DOC_STATUS = CURRENT_PRODUCT
BUSINESS_ID = B54
CANONICAL_SOURCE = apps/korean-ai-code-agent/**
CANONICAL_PRODUCT_NAME = Padiem Claw
PACKAGE_CLI = korean-ai-code-agent / kagent
LAST_VERIFIED = 2026-09-08
```

Padiem Claw is Padiem's coding-agent product surface. It owns repository/task/run/workspace/GitHub product semantics and consumes shared Padiem AI platform capabilities instead of recreating them.

Canonical platform references:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/governance/LEGACY_AI_TERMINOLOGY_MAP.md`

## Current architecture boundary

```text
Padiem Claw product UX / CLI / future first-party surfaces
        │
        ▼
B54 task / run / repository / workspace adapter
        │
        ▼
IP-ENGINE · Padiem AI Engine
cross-runtime trusted service boundary
        │
        ▼
IP-CORE · Padiem AI Core
Agent / Tool / Skill / approval / recovery / orchestration semantics
        │
        ▼
B14 · Korean AI Platform
Provider / model routing and execution
        │
        ▼
Provider / Model

IP-CONTROL = identity / tenant / entitlement / usage / audit where integrated
```

`P01` is a legacy identifier for the shared Core concept. Current documentation uses **IP-CORE**. Historical documents may retain `P01` only as dated evidence.

## B54 owns

- task identity and product-visible task intent;
- repository and requested revision references;
- product run/workspace lifecycle projection;
- local workspace and sandbox resource requests;
- product-specific diff/test/review/GitHub workflow;
- CLI/TUI and future Claw-specific presentation;
- product-local permission prompts and user-facing copy.

## B54 must not own

- generic Agent planning/runtime semantics;
- generic Tool or Connector authorization semantics;
- reusable Skill package/runtime semantics;
- generic approval/recovery/delegation/orchestration semantics;
- Provider/model registry or inference credentials;
- a product-local generic AI router;
- canonical identity/tenant/entitlement/usage/audit truth.

Those authorities remain with IP-CORE, IP-ENGINE, B14 and IP-CONTROL according to the vertical-stack contract.

## Current source/runtime truth

The repository contains a hardened Phase 1 CLI/TUI and later boundary refactors. Source presence does not prove live cloud-agent or provider activation.

```text
SOURCE_PRESENT
!= ENGINE_BINDING_READY
!= CORE_RUNTIME_COMPOSED
!= PROVIDER_READY
!= CLOUD_SANDBOX_READY
!= PRODUCTION_ACTIVE
```

The deterministic B14 preview adapter is test/architecture evidence only. It does not establish live Provider execution or model-routing authority inside B54.

A sandbox lease or prepared workspace is also not proof that an agent has started:

```text
SANDBOX_ALLOCATED
!= AGENT_RUNNING
```

## Run lifecycle

B54 may project a product lifecycle such as:

```text
queued
→ preparing
→ running
↔ waiting_approval
→ completed | failed | cancelled
```

This is a product-facing lifecycle projection. Shared execution, approval, recovery and orchestration semantics remain IP-CORE-owned and cross-runtime projection remains IP-ENGINE-owned.

## Safety defaults

```text
repository read = allowed after repository selection
file write       = explicit permission
command execution = explicit permission + allowlist
network          = off unless explicitly authorized by the accepted runtime contract
git mutation     = off by default
push/merge/deploy = not implied by product source
```

Raw Provider credentials must never be present in browser/product state, product task contracts, logs or committed documentation.

## Model/tier relationship

Claw does not own Padiem Plus/Pro/Max route truth. Current shared Padiem tier declarations are owned by:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

B14 remains final executability and actual Provider/model execution authority. Any B54 adapter may consume an accepted route/profile but must not redefine the route catalog.

## Historical detail

The pre-unification README, including Phase 1/2 implementation detail and legacy `P01` terminology, is preserved without loss at:

```text
docs/history/2026-09-02/PADIEM_CLAW_README.snapshot.md
```

Use that file for historical implementation evidence only. For current architecture and ownership, this README plus the canonical platform documents above take precedence.
