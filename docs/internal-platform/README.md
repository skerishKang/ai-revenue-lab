# Padiem Internal Platform — AI Stack Index

Internal Platform IDs identify shared technical infrastructure. They are **not Business numbers**.

## Canonical registry

| ID | Name | Source authority | Role |
|---|---|---|---|
| `IP-CORE` | Padiem AI Core | `packages/padiem-ai-core/**` | reusable AI contracts, execution semantics, evidence/grounding, Web/Research, Tool/Connector, Memory/RAG, Skill, Agent and orchestration semantics |
| `IP-ENGINE` | Padiem AI Engine | `apps/padiem-ai-engine/**` | trusted cross-runtime service boundary and versioned projection of Core capabilities |
| `IP-CONTROL` | Padiem Control Plane | `packages/padiem-control-plane/**` | canonical identity/subject, tenant/workspace, entitlement, usage/credits/billing and shared audit/security authority |
| `IP-SIDECAR` | Padiem Embedded AI Runtime | planned/shared embedded-runtime authority | reusable embedded panel/context/bootstrap/event presentation primitives when a host product needs them |

## Numbered platform dependency

```text
B14 = Korean AI Platform / General AI Router Platform
```

B14 remains a numbered Business. It owns provider/model routing and external model execution and is referenced by the Internal Platform; it is not renumbered as `IP-*`.

## Canonical cross-runtime path

```text
Product / Business
  -> Product Adapter
  -> IP-ENGINE
  -> IP-CORE
  -> B14
  -> Provider / Model
```

IP-CONTROL is cross-cutting authority rather than a mandatory sequential transport hop.

IP-SIDECAR appears between a host/product adapter and IP-ENGINE only when reusable embedded delivery is required.

An accepted same-runtime consumer may call IP-CORE directly, but the ownership model remains unchanged.

## Product examples

- **B62 Padiem Chat** — standalone general AI/product shell.
- **B54 Padiem Claw** — agent/business-work product consuming shared Agent/Tool/Skill/Connector/Memory semantics.
- **B53 Padiem Sidecar** — commercial embedded-AI product using IP-SIDECAR when that shared runtime is implemented/activated.
- **B61 StoryMemory** — reading/memory AI product with private application-source authority and a bounded Product Adapter.
- **B30 / 400 AI Finder** and other AI products — reuse shared Web/Research/Evidence/Engine/Core capability rather than fork it.

## Authority

Current cross-layer architecture:

`../architecture/PADIEM_AI_VERTICAL_STACK.md`

Layer-specific README/contracts may specialize their own boundaries. Runtime availability and Production state still require current source/manifest/deployment evidence.