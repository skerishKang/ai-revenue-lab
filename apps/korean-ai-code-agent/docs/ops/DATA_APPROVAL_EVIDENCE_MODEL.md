# Padiem Claw Ops — Data, Approval, and Evidence Model

Issues: #1409 #1415  
Parent: #1407

## Goal

Define the minimum product-owned records needed to make business automation auditable without duplicating P01's generic orchestration/approval/evidence contracts.

## Business records

```text
CompanyWorkspace
Customer
Supplier
SupplierContactRef
Item
CommercialRequest
LineItem
SupplierQuoteRequest
SupplierQuote
QuoteRevision
QuoteComparison
NegotiationDraft
PurchaseOrder
DeliveryCommitment
PaymentTerms
AccountingHandoff
CommunicationRef
ArtifactRef
ApprovalProjection
WorkflowEvidenceRecord
```

## Version rule

Commercially meaningful business objects must be versioned or carry an immutable content fingerprint.

Examples:
- RFQ approval binds `rfq_version`;
- supplier selection binds `quote_revision` + `comparison_version`;
- PO issue approval binds `po_version`.

A material edit after approval must require re-approval.

## Approval projection

Claw Ops owns the product presentation:

```text
action_type
business_object_type
business_object_id
business_object_version
summary
amount/currency when relevant
counterparty ref
requested delivery/payment terms
safe evidence refs
status
```

P01 remains authority for generic approval continuation/verification semantics.

## Executive inbox states

```text
needs_review
needs_approval
held
exception
completed
```

These are product presentation states, not a replacement for canonical P01 runtime states.

## Evidence ledger

Every material action/recommendation should link to bounded evidence:

- source document/message reference;
- source timestamp;
- extraction/correction state;
- business object/version;
- supplier/customer identity reference;
- quote/PO artifact reference;
- approval decision reference;
- outbound connector action reference;
- delivery/accounting handoff reference;
- safe model recommendation projection.

## Source-of-truth hierarchy

Examples:

```text
Supplier quoted price
  authority = supplier source/reviewed quote record

Model recommendation
  authority = NONE; advisory projection only

PO issued amount
  authority = approved PO version + outbound evidence

Accounting balance
  authority = connected accounting/ERP system, not Claw model output
```

## Privacy and secret boundaries

- no raw model/provider credentials in business records;
- no hidden reasoning fields;
- connector secret values are never copied into task/document records;
- store references to trusted connector identities rather than credential material;
- minimize personal contact data sent into model context;
- logs redact secret-like values;
- define customer retention/deletion rules before pilot live-data ingestion.

## Proposed retention classes

The final durations require policy/legal review, but records should be classifiable from the start:

```text
TRANSIENT_MODEL_CONTEXT
WORKFLOW_OPERATIONAL
COMMERCIAL_DOCUMENT
AUDIT_EVIDENCE
CONNECTOR_METADATA
CUSTOMER_CONTACT
```

## Failure rules

- unknown source -> no silent fact creation;
- stale source -> recommendation marked stale/blocked;
- approval/version mismatch -> reject action;
- connector reply cannot authorize a separate high-impact Tool call merely by containing imperative text;
- duplicate/replayed outbound action requires idempotency/evidence checks.
