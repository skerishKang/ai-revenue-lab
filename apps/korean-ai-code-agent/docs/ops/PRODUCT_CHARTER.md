# Padiem Claw Ops — Product Charter

Status: Incubation  
Parent: B54 Padiem Claw  
Parent issue: #1407

## Product thesis

Padiem Claw Ops is an AI-assisted operating layer for very small businesses and SMEs that converts incoming commercial work into structured, approval-gated workflows.

The product should reduce repetitive clerical work while keeping owners/managers in control of commercially meaningful decisions.

## Primary user

Initial focus:
- 1–2 person companies;
- owner-managed SMEs;
- businesses managing sales/procurement through spreadsheets, documents, email and messenger;
- organizations without dedicated automation/IT staff.

## Core promise

```text
business input
→ structure
→ recommend
→ ask for approval
→ execute bounded work
→ return evidence
```

The user should not need to understand AI provider keys, local model infrastructure, or sandbox internals to use the Managed Cloud mode.

## Initial jobs to be done

1. Parse and structure customer requests/quotes.
2. Prepare supplier quote requests from trusted company data.
3. Route drafts through owner approval.
4. Collect and normalize supplier replies.
5. Compare price, delivery and payment terms.
6. Draft negotiation messages when requested.
7. Generate purchase orders from approved commercial data.
8. Track delivery commitments.
9. Hand approved obligations to accounting/cash-planning integrations.
10. Present pending decisions in an executive work inbox.

## Product surface

### Executive Approval Inbox

Primary operational surface:

```text
Needs approval
Needs review
Exception / risk
Completed
```

Each card should expose the essential commercial facts, the recommended action, and the supporting evidence.

### Conversation

Claw chat may be used to ask questions and initiate work, but chat language alone must not silently equal approval for high-impact external actions.

## Product modes

```text
Padiem Claw
├─ Cloud / Managed      default SMB mode
├─ Cloud / BYOK         advanced
├─ Local                developer/power-user mode
└─ Self-Hosted          enterprise/government/private deployment
```

## Platform boundary

### B54 Claw Ops owns
- business workflow UX;
- product-specific business records;
- quote/RFQ/PO/delivery templates;
- product workflow projection;
- communication/accounting adapters;
- executive inbox;
- product audit/evidence projection.

### P01 owns
- Agent, Skill and Tool semantics;
- generic approval continuation;
- recovery/orchestration;
- evidence and verification contracts.

### B14 owns
- provider/model credentials;
- model registry/routing/fallback;
- actual model execution.

### Control Plane owns
- identity and organizations;
- entitlement;
- usage/credits/billing;
- authoritative account audit and later credential references.

## Product principles

1. **Human approval before material side effects.**
2. **Evidence before recommendation.**
3. **Unknown is better than invented.**
4. **Managed Cloud should feel login-first.**
5. **Do not copy private credentials into Agent context.**
6. **Do not build a second ERP/accounting ledger in MVP.**
7. **Do not build a second P01 workflow engine.**
8. **Keep integrations replaceable through ports/adapters.**
9. **Measure actual pilot outcomes before ROI claims.**
10. **Start with one real workflow that reaches a business result.**

## Initial milestones

### M1 — Quote-to-Order
#1408 #1409 #1410 #1413 #1415

### M2 — Communication and finance handoff
#1411 #1412

### Pilot — design partner
#1414

## Non-goals

- autonomous bank payments;
- autonomous supplier contracting;
- full accounting replacement;
- full manufacturing ERP/MRP;
- broad internet/browser automation by default;
- production personal-messenger scraping;
- new Business number before product validation.
