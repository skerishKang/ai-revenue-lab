# Padiem Claw Ops — Documentation Index

Status: **Incubation / design-partner discovery**  
Parent product: **B54 Padiem Claw**  
Parent issue: **#1407**

## Purpose

`Padiem Claw Ops` is a proposed small-business operations vertical built on Padiem Claw. It does **not** create a new Business number, a second Agent runtime, or a replacement ERP in the first release.

The initial opportunity was extracted from a 2026-09-02 design-partner call about sales/procurement automation, supplier quote requests, approvals, purchase orders, delivery, accounting handoff, cash planning, and a six-month company pilot.

Public documentation is deliberately redacted. Names, phone numbers, and private contact details are not copied into this repository.

## Canonical documents

1. [`DISCOVERY_CALL_REDACTED.md`](./DISCOVERY_CALL_REDACTED.md) — what the source call directly supports and what is later product inference.
2. [`PRODUCT_CHARTER.md`](./PRODUCT_CHARTER.md) — product thesis, target user, scope and P01/B14/Control Plane boundaries.
3. [`QUOTE_TO_ORDER_MVP.md`](./QUOTE_TO_ORDER_MVP.md) — first end-to-end workflow.
4. [`DATA_APPROVAL_EVIDENCE_MODEL.md`](./DATA_APPROVAL_EVIDENCE_MODEL.md) — business records, approvals and evidence linkage.
5. [`MANAGED_CLOUD_AND_MODES.md`](./MANAGED_CLOUD_AND_MODES.md) — Managed Cloud, BYOK, Local and Self-Hosted modes.
6. [`PILOT_AND_COMMERCIALIZATION.md`](./PILOT_AND_COMMERCIALIZATION.md) — design-partner pilot, KPIs and commercialization/public-program evidence.
7. [`index.html`](./index.html) — read-only visual overview.

## Issue map

```text
#1407  Claw Ops parent / incubation
├─ #1408  Quote-to-Order MVP
├─ #1409  Executive approval inbox
├─ #1410  Supplier comparison + negotiation
├─ #1411  Communication connectors
├─ #1412  Finance/cash-flow handoff
├─ #1413  Managed Cloud onboarding
├─ #1414  Six-month design-partner pilot
└─ #1415  Business workflow data + evidence ledger
```

## Authority rule

```text
B54 Claw Ops
  owns SMB workflow UX + business records + product adapters

P01
  owns generic Agent / Skill / Tool / Approval / Evidence / Orchestration semantics

B14
  owns model/provider credentials, routing and execution

Control Plane
  owns identity, org, entitlement, usage, credits/billing and authoritative account audit
```

## Initial product promise

> Turn incoming commercial requests and supplier communication into structured, approval-gated work so a small-business owner can focus on decisions instead of repetitive document relay and re-entry.

## Non-goals for the first pilot

- full ERP replacement;
- autonomous purchasing/payment;
- autonomous commercial negotiation commitment;
- personal-messenger screen scraping;
- new shared Agent runtime;
- new Business number;
- production rollout before design-partner evidence and security gates.
