# B35 Parallel Workstream and Gate Matrix

## 1. Execution topology

```text
CENTRAL / W0 #1502
  authority + gap lock
        │
        ├──────────────┬──────────────┐
        │              │              │
LANE A #1503     LANE B #1504     LANE C #1505
commercial       builder +         independent
source           regeneration      QA harness
        │              │              │
        └──── accepted source ─────────┘
                       │
                exact regenerated
                     package
                       │
                   #1507 W4
                 pixel visual QA
                       │
                   #1508 W5
                  final closeout
```

## 2. Model allocation

Use three same-model workers after W0 locks authority.

### Model A — Commercial Source CTO

Owns Issue #1503.

Allowed intent:
- current commercial markdown source only;
- V3.1 terminology and product-story reconciliation;
- offer/scope consistency;
- source-level validation.

Prohibited:
- generator/binary writes;
- visual QA self-approval;
- B35 product UI redesign;
- customer send.

### Model B — Artifact Build CTO

Owns Issue #1504.

Allowed intent:
- selective recovery of #359 build scripts;
- generator rebase/reconciliation;
- deterministic artifact generation;
- generation manifest and output hashes;
- final regeneration after accepted Lane A source.

Prohibited:
- rewriting product/commercial truth to simplify generation;
- declaring visual or customer readiness;
- customer send.

### Model C — Independent Verification CTO

Owns Issue #1505.

Allowed intent:
- QA harnesses and validators;
- structural/text-fit/formula/source mapping checks;
- stale-artifact and exact-revision trace checks;
- final machine-verdict report.

Prohibited:
- silently editing commercial copy or generated artifacts to obtain PASS;
- using historical QA as current evidence;
- pixel approval or customer send.

## 3. Gate sequence

### G0 — Authority gate

Owner: CENTRAL / #1502.

Pass when:

```text
CURRENT_MAIN_FRESH = YES
PRODUCT_AUTHORITY_IDENTIFIED = YES
LEGACY_REUSE_MATRIX_COMPLETE = YES
PATH_OWNERSHIP_LOCKED = YES
COLLISION_AUDIT_COMPLETE = YES
```

### G1 — Commercial source gate

Owner: Lane A / #1503.

Pass when:

```text
V3_1_STORY_ALIGNMENT = PASS
CROSS_DOC_TERMINOLOGY = PASS
OFFER_SCOPE_CONSISTENCY = PASS
PRICE_HYPOTHESIS_BOUNDARY = PASS
STALE_PRODUCT_IDENTITY = 0
```

### G2 — Generation gate

Owner: Lane B / #1504.

Pass when:

```text
ACCEPTED_SOURCE_REVISION_RECORDED = YES
DETERMINISTIC_BUILD = PASS
REQUIRED_OUTPUTS_PRESENT = PASS
GENERATION_MANIFEST_PRESENT = PASS
OUTPUT_HASHES_PRESENT = PASS
```

### G3 — Machine QA gate

Owner: Lane C / #1505.

Pass when:

```text
PACKAGE_INVENTORY_PASS
SOURCE_MAPPING_PASS
STRUCTURAL_QA_PASS
FORMULA_QA_PASS
TEXT_FIT_PASS
STALE_ARTIFACT_REJECTION_PASS
PRIVATE_DATA_BOUNDARY_PASS
EXACT_REVISION_TRACE_PASS
```

### G4 — Pixel/customer comprehension gate

Owner: CENTRAL review / #1507.

Pass when all customer-visible artifacts have fresh visual evidence and no blocking clipping, overflow, overlap, stale identity, unreadable table/form or contradictory customer copy remains.

### G5 — Reusable master closeout

Owner: CENTRAL / #1508.

Final allowed master status:

```text
MASTER_PACKAGE_NOT_READY
or
MASTER_PACKAGE_CONDITIONALLY_READY
```

`AUTHORIZED_FOR_NAMED_CUSTOMER_SEND` is not granted by this closeout program.

## 4. Failure routing

```text
copy/product-story defect found by B/C/W4
→ return to Lane A

generator/layout/render defect found by C/W4
→ return to Lane B

validator defect or false signal
→ return to Lane C

product-contract contradiction requiring B35 UI/product change
→ STOP closeout widening and escalate to CENTRAL
```

## 5. Branch/PR rule

Each parallel lane uses a fresh branch from the then-current `main` or an explicitly accepted integration base after fresh collision review.

Default:

```text
PR = OPEN / DRAFT
MERGE = NO until exact-head checks and CENTRAL acceptance
PRODUCTION = NO
CUSTOMER_SEND = NO
```

Do not stack unrelated lanes merely for convenience. If a lane must consume another lane's accepted revision, merge-forward or branch from the accepted integration head only after the dependency is explicit.

## 6. Report contract for each model

Every lane report must end with:

```text
CURRENT_MAIN
ISSUE
BRANCH
BASE_SHA
HEAD_SHA
CHANGED_PATHS
DEPENDENCY_REVISION
TESTS_OR_VALIDATORS
EXACT_HEAD_CI
BLOCKERS
OUT_OF_SCOPE_MUTATION = NONE | <exact list>
CUSTOMER_SEND = NO
PRODUCTION_MUTATION = NO
FINAL_DISPOSITION
```
