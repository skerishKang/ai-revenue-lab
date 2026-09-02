# Padiem Claw Ops — Quote-to-Order MVP

Issue: #1408  
Parent: #1407

## Objective

Prove one end-to-end business workflow that produces a real operational result while preserving explicit human control.

```text
customer commercial request
→ structured line items
→ supplier RFQ drafts
→ approval
→ supplier replies
→ normalized comparison
→ selection / negotiation approval
→ purchase order
→ final approval
→ delivery/audit record
```

## Stage 1 — Intake

Accepted inputs can be introduced incrementally:
- manual structured form;
- PDF document;
- spreadsheet;
- approved email/message attachment.

Canonical output should include:
- source artifact reference;
- customer/workspace reference;
- item/description;
- quantity/unit;
- requested date;
- commercial notes;
- extracted confidence/correction state.

Unknown values stay unknown. The model must not silently invent SKU, supplier, price or due date.

## Stage 2 — Supplier candidate resolution

Supplier candidates must come from trusted company data or an explicitly reviewed lookup source.

The product should support:
- supplier-item relationship;
- preferred supplier status;
- historical prices as evidence, not guaranteed current offers;
- settlement/payment terms;
- contact/channel reference;
- active/inactive status.

## Stage 3 — RFQ generation

For each approved candidate supplier, create a bounded RFQ draft containing only the required commercial fields.

Before outbound delivery:
- show supplier;
- show item/quantity;
- show requested delivery date;
- show any target/notes;
- bind the approval to the exact draft version.

## Stage 4 — Supplier reply ingestion

Each reply is linked to the exact RFQ and source communication.

Normalized fields:
- supplier;
- quote/revision id;
- line prices;
- total price;
- tax/shipping if stated;
- delivery promise;
- payment terms;
- validity period if stated;
- exceptions;
- source timestamp/artifact.

## Stage 5 — Comparison

Comparison dimensions:

```text
price
+ delivery
+ payment/credit terms
+ trusted historical evidence
+ completeness / exceptions
```

The system may label a recommendation such as `lowest_price`, `fastest_delivery`, `best_cashflow_fit` or `balanced`, but must expose the underlying fields.

## Stage 6 — Negotiation option

If requested, Claw creates negotiation drafts using trusted quote/comparison data.

Rules:
- no fabricated competing offers;
- no autonomous commitment;
- target price/range is visible to the approver;
- outbound send requires approval;
- new supplier response creates a new quote revision.

## Stage 7 — Supplier selection

Selection approval binds:
- comparison version;
- supplier quote revision;
- amount;
- delivery;
- payment terms.

Any material upstream change should invalidate stale approval.

## Stage 8 — Purchase Order

Generate an auditable purchase-order artifact from the approved selection.

The PO must not be issued merely because a language model generated text. Final issue/send requires an explicit trusted decision.

## Stage 9 — Delivery + handoff

After PO issue:
- record promised delivery;
- surface overdue/changed delivery exceptions;
- create accounting/cash-planning handoff data;
- preserve evidence links.

## Definition of Done

A pilot transaction is complete only when:

```text
input source preserved
AND structured data reviewed
AND RFQ approval recorded
AND supplier replies attributable
AND comparison evidence visible
AND supplier selection approved
AND PO version approved
AND outbound action evidenced
AND delivery/payment commitment recorded
```

## Deferred

- autonomous purchasing;
- broad inventory/MRP;
- bank payments;
- statutory accounting;
- multi-company marketplace;
- autonomous contract negotiation;
- predictive optimization without reliable historical data.
