# B35 Independent QA Harness — Lane C #1505

```text
LANE = C / Independent Package QA
ISSUE = #1505
BRANCH = feat/b35-w3-independent-qa-v31
BASE_SHA = eae88e0066c1b119bfa6c75d8b16c127b0137e5e
OPERATING_AUTHORITY = docs/operations/business-35/** on main
PRODUCT_AUTHORITY = reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
LEGACY_VALIDATOR_LINEAGE = Draft PR #359 @ ef343f420661cda5f86cc2848404bca8f1dffe54
FINAL_SOURCE_DEPENDENCY = accepted exact head from #1503
FINAL_PACKAGE_DEPENDENCY = exact regenerated package from #1504
```

Independent machine-checkable acceptance surface for B35 closeout. This harness does **not** author commercial copy and does **not** regenerate final customer artifacts.

## Ownership

Owns only the independent QA harness, validator logic and machine-verdict evidence for #1505. Validator ideas/code from #359 are selectively recovered, but historical PASS results do not transfer.

## Required verdicts

```
PACKAGE_INVENTORY_PASS
SOURCE_MAPPING_PASS
STRUCTURAL_QA_PASS
FORMULA_QA_PASS
TEXT_FIT_PASS
STALE_ARTIFACT_REJECTION_PASS
PRIVATE_DATA_BOUNDARY_PASS
EXACT_REVISION_TRACE_PASS
```

A failed or unavailable check remains failed/unavailable; do not convert it to PASS by inference.

## Usage

```bash
# Default paths (fresh main layout)
python tools/b35-independent-qa/validate_b35_independent_qa.py

# Explicit roots (for parallel-lane or v3-regenerated layouts)
python tools/b35-independent-qa/validate_b35_independent_qa.py \
  --commercial-root docs/commercial/business-35-ai-media-education-dx \
  --package-root docs/commercial/business-35-ai-media-education-dx/customer-package \
  --product-contract reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md \
  --output-json tools/b35-independent-qa/evidence/qa_report.json \
  --output-md tools/b35-independent-qa/evidence/qa_report.md

# V3 review draft layout
python tools/b35-independent-qa/validate_b35_independent_qa.py \
  --package-root docs/commercial/business-35-ai-media-education-dx/customer-package/v3-regenerated \
  --manifest docs/commercial/business-35-ai-media-education-dx/customer-package/v3-regenerated/MANIFEST_V3_1.json

# Run via harness (collects env, hashes, writes evidence)
python tools/b35-independent-qa/run_qa.py --pretty
```

## Independence rule

The harness may be built in parallel. Final PASS is forbidden until it runs against the exact accepted #1503 source and exact #1504 regenerated package. The validator never edits commercial copy or generated artifacts merely to produce PASS; defects are routed to the owning lane.

## References

- `docs/operations/business-35/B35_AUTHORITY_AND_ARTIFACT_MATRIX.md`
- `docs/operations/business-35/B35_COMMERCIAL_CLOSEOUT_OPERATING_PLAN.md`
- `docs/operations/business-35/B35_PARALLEL_WORKSTREAM_AND_GATE_MATRIX.md`
- `reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md`
- Legacy validator: `feat/business-35-customer-facing-package:validation/validate_customer_package.py` (PR #359)
