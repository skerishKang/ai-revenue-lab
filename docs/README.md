# AI Revenue Lab Documentation Authority Index

This page is the entry point for repository documentation.

The repository contains both **current authority** and **historical/point-in-time evidence**. A dated issue note, phase charter, old implementation report, or closed-program document must not silently override a newer canonical architecture or the current merged runtime.

## Authority order

Use the narrowest current authority that applies:

1. **Business numbering / portfolio identity** — `portfolio/BUSINESS_REGISTRY.md` and accepted successor-lineage documents.
2. **Padiem shared AI architecture** — `architecture/PADIEM_AI_VERTICAL_STACK.md`.
3. **Layer/product boundary documents** — current README/contract under the owning source path.
4. **Operations/release policy** — `operations/README.md` and the current policy documents it indexes.
5. **Runtime availability** — current merged source, contract manifest, tests, and exact deployment/readback evidence. Source presence is not Production activation.
6. **Historical evidence** — dated audits, phase charters, issue-specific snapshots and superseded proposals. These explain how the system evolved; they do not redefine current authority.

If two current-looking documents conflict, do not average them. Reconcile them against the owning layer, current merged source, and the canonical vertical-stack boundary.

## Documentation families

### Architecture

Start with:

- `architecture/README.md` — architecture document classification.
- `architecture/PADIEM_AI_VERTICAL_STACK.md` — current Padiem AI vertical stack and ownership/adoption model.

The canonical cross-runtime direction is:

```text
Product / Business
  -> Product Adapter
  -> IP-ENGINE
  -> IP-CORE
  -> B14 Router Platform
  -> Provider / Model
```

`IP-CONTROL` is cross-cutting identity/tenant/entitlement/usage/billing/audit authority rather than a mandatory sequential hop in every model request. `IP-SIDECAR` is the reusable embedded-delivery layer when a host product needs one.

A same-runtime/library consumer may use IP-CORE directly only where an accepted architecture explicitly permits it.

### Internal Platform

- `internal-platform/README.md`

Canonical IDs:

```text
IP-CORE    = Padiem AI Core
IP-ENGINE  = Padiem AI Engine
IP-CONTROL = Padiem Control Plane
IP-SIDECAR = Padiem Embedded AI Runtime (planned/shared embedded layer)
```

B14 remains a numbered Business / Router Platform dependency and is not renumbered as an Internal Platform component.

### Product

`product/**` contains product contracts, commercial/product packs, and portfolio presentation contracts.

Product documents specialize the shared stack; they cannot move generic AI semantics, cross-runtime transport, provider routing, or canonical account/entitlement truth into a product merely for convenience.

### Operations

- `operations/README.md`

Operations documents define development, validation, release, rollback, evidence and incident procedures. P01/E9/issue-numbered operational files are often point-in-time execution evidence; their filenames are retained for traceability and do not create a new architecture layer.

### Portfolio / decisions / governance

These own Business numbering, portfolio relationships, organization-wide decisions and governance. They should reference the Padiem AI vertical stack where a Business consumes shared AI, rather than restating a competing stack.

### Experiments / research / history

`experiments/**`, historical phase documents, dated audits, provider handoffs and old PR/issue snapshots remain useful evidence. Treat their route/model/provider/status claims as historical unless a current authority explicitly adopts them.

## Current AI-family adoption rule

A product that needs AI should first classify its requirement:

```text
DOMAIN / PRODUCT UX                  -> Product / Product Adapter
REUSABLE AI SEMANTICS               -> IP-CORE
CROSS-RUNTIME SERVICE PROJECTION     -> IP-ENGINE
MODEL / PROVIDER ROUTING + EXECUTION -> B14
IDENTITY / TENANT / ENTITLEMENT      -> IP-CONTROL
EMBEDDED HOST DELIVERY               -> IP-SIDECAR when applicable
```

Do not create product-local copies of shared Agent, Tool, Connector, Skill, Memory/RAG, Evidence, provider registry, routing, credential, identity, entitlement or billing authority because an integration is temporarily incomplete.

## Truthfulness rule

Always distinguish:

```text
DOCUMENTED
SOURCE_PRESENT
TESTED
MERGED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

No earlier state implies a later one.