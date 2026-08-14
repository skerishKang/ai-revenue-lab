# Workflow Status Model

- Status: canonical
- Authority: Issue #148

This status model separates implementation progress, validation evidence, CTO readiness, owner decisions, merge, and Production. Do not collapse them into one “done” flag.

## Implementation

```text
NOT_STARTED
IN_PROGRESS
IMPLEMENTED_SELF_CHECK_PENDING
IMPLEMENTED_SELF_CHECKED
BLOCKED
SUPERSEDED
```

`IMPLEMENTED_SELF_CHECKED` means the implementation actor ran its own checks. It is not independent validation.

## Independent validation

```text
NOT_REQUIRED
PENDING
BLOCKED
FAILED
PASSED
INVALIDATED_BY_NEW_REVISION
```

Use `PASSED` only when the required independent validator tested the exact revision and did not create a new product-source revision during that validation.

## CI

```text
NOT_CONFIGURED
NOT_REQUIRED
PENDING
FAILED
PASSED
```

CI status never substitutes for a different required evidence type.

## Web CTO final review

```text
NOT_REVIEWED
NOT_READY
CONDITIONALLY_READY
READY
```

- `NOT_READY` — one or more required acceptance criteria fail or evidence is materially insufficient.
- `CONDITIONALLY_READY` — the reviewed source is acceptable within explicitly recorded remaining conditions that do not misrepresent completion.
- `READY` — the current exact head satisfies the technical/review contract and all required pre-merge evidence.

These statuses do not automatically imply owner visual approval, merge, deployment, or commercial approval.

## Owner decision

Use only when the work contract reserves a material decision to the owner.

```text
NOT_REQUIRED
PENDING
APPROVED
REJECTED
```

A Web CTO may make a delegated product/design decision when the owner explicitly delegates that authority. Record it as `CTO_DELEGATED_DECISION`, not as retroactive `OWNER_APPROVED` evidence.

## Merge

```text
NOT_AUTHORIZED
AUTHORIZED
MERGED
CLOSED_UNMERGED
```

Use expected-head protection when merging a reviewed PR.

## Production

```text
NOT_APPLICABLE
NOT_AUTHORIZED
AWAITING_GIT_DEPLOYMENT
DEPLOYED_UNVERIFIED
ACCEPTED
FAILED
RESTORED
```

Follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

## Product evidence stage

A Business/work item may declare one current evidence target:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

These are not mandatory sequential gates. The work contract selects the stage that answers the current uncertainty.

## Evidence-dimension verdicts

Use separate verdicts when relevant:

```text
TECHNICAL_UI_PASS
VISUAL_QUALITY_PASS
UX_PASS
BACKEND_RUNTIME_PASS
SECURITY_PASS
MARKET_REFERENCE_PASS
INVESTOR_DEMO_PASS
COMMERCIAL_EVIDENCE_PASS
```

Never infer one from another.

## Revision rule

Every status that depends on source behavior records the exact SHA. A new commit changes the revision identity and may move validation/review back to `PENDING` or `INVALIDATED_BY_NEW_REVISION`.
