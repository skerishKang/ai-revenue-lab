---
name: Web CTO work order
about: Web CTO work contract for a Web Developer / local implementation actor
title: "[AREA] <smallest product outcome this revision must prove>"
labels: ''
assignees: ''
---

<!--
Canonical work-order template: docs/operations/templates/CTO_WORK_ORDER.md
A work contract that does not record non-goals and forbidden paths cannot be
audited after implementation. Fill every field or write NOT_REQUIRED + reason.
-->

## Authority / revision

- Owner request / parent issue:
- Product-evidence stage: `PRODUCT_FRAMED / COMPETITIVE_DEMO / INVESTOR_DEMO / MVP_VERTICAL_SLICE / SERVICE_LED_PILOT / RUNTIME_PILOT / COMMERCIAL_HARDENING / OPERATING_PRODUCT`
- Exact current base SHA (not `latest main`):
- Target branch:

## Objective

State the smallest user/product outcome this revision must prove.

## Scope

- Allowed paths:
- Forbidden paths:
- **Non-goals (required — do not leave empty):**
- Existing behavior/contracts to preserve:
- Data/secret boundary:

## Required behavior

1.
2.

## Acceptance criteria

1.
2.

## Required tests / checks

- Automated commands:
- CI/checks:
- Browser/local validation:

## Boundaries

```text
PROVIDER_CALLS = 0
STORAGE_MUTATION = 0
PRODUCTION_MUTATION = 0
OWNER_DECISION_REQUIRED = NO/YES
```

## Role plan

- Web CTO:
- Web Developer:
- Independent Local Validator required? yes/no + reason:

> Implementation actor and independent Local Validator must not be the same
> actor for the same revision.

## Evidence required in the implementation report

- exact base SHA and head SHA;
- exact changed files;
- commands, exit codes and pass/fail/skip counts;
- truthful reporting of failed/skipped/unexecuted checks;
- self-checks labelled `IMPLEMENTATION_SELF_CHECK`.
