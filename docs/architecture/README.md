# Architecture Documentation Index

## Current cross-layer authority

The current Padiem AI family architecture is defined by:

- `PADIEM_AI_VERTICAL_STACK.md` — canonical layer topology, ownership, product adoption and status semantics.

Layer-specific documents may add detail, but must not contradict that boundary.

## Current specialized architecture

Issue/product-specific files in this directory define bounded contracts such as Claw automation/connector/export boundaries, retrieval conformance, or product integration seams. They remain authoritative only for their specialized subject and only while consistent with the current owner layer.

Examples include:

- `B54_CLAW_AUTOMATION_BOUNDARY_2058.md`
- `B54_CLAW_CONNECTOR_ACTION_APPROVAL_STATES_2089.md`
- `B54_CLAW_CONTROL_PLANE_GOOGLE_OAUTH_BOUNDARY_1908.md`
- `B54_CLAW_DOCUMENT_EXPORT_2016.md`
- `B54_CLAW_MANUAL_INTAKE_2056.md`
- `B54_CLOUD_M1_SANDBOX_THREAT_MODEL_1405.md`
- `PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`
- `PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`

These documents do not independently redefine IP-CORE, IP-ENGINE, B14, IP-CONTROL, IP-SIDECAR, or another product's ownership.

## Historical / point-in-time architecture evidence

Documents with an explicit audit date/version/old program topology remain useful evidence but are not automatically current architecture authority.

In particular:

- `PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` — 2026-09-01 capability/ownership snapshot. Superseded for cross-layer topology and current Padiem route policy by `PADIEM_AI_VERTICAL_STACK.md`; retain it for the detailed capability inventory and audit history.
- `B62_P01_B14_CONTROL_PLANE_OWNERSHIP_REVIEW_20260831.md` — dated ownership review; retain as decision history.

`P01` in older filenames/issues is retained for traceability. The canonical Internal Platform names are IP-CORE / Padiem AI Core and IP-ENGINE / Padiem AI Engine.

## Architecture invariants

```text
PRODUCT OWNS DOMAIN AND UX.
IP-CORE OWNS REUSABLE AI SEMANTICS.
IP-ENGINE EXPOSES SHARED AI ACROSS RUNTIMES.
B14 OWNS MODEL/PROVIDER ROUTING AND EXECUTION.
IP-CONTROL OWNS SHARED ACCOUNT/ENTITLEMENT/USAGE TRUTH.
IP-SIDECAR OWNS REUSABLE EMBEDDED DELIVERY WHEN APPLICABLE.
```

Cross-runtime default:

```text
Product -> Product Adapter -> IP-ENGINE -> IP-CORE -> B14 -> Provider/Model
```

An accepted same-runtime/library integration may use `Product -> Adapter -> IP-CORE -> B14`, but that is an implementation seam, not permission to bypass ownership or turn the product into a shared service.

## Status rule

Architecture documentation describes ownership. Runtime source/manifest/test/deployment evidence describes availability. Never convert `source exists` into `Production active` through documentation alone.