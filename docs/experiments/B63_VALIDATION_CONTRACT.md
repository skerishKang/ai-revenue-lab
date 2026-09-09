# B63 Validation Contract

Status: **proposed Business / validation only**  
Authority: Issues #731, #735, #736, #753

This contract turns B63's pre-build customer and technical gates into machine-readable evidence. It does not register B63 canonically and does not authorize a product runtime.

## Inputs

The evaluator consumes two JSON files:

1. `b63.customer-discovery.v1`
2. `b63.r0-result.v1`

The gate configuration is versioned at:

`docs/experiments/b63/validation-gates.json`

## Customer gate

Current thresholds are copied from Issue #735 and are deliberately conjunctive:

- total interviews >= 5
- hospital interviews >= 3
- interviews with `problem_severity = 2` >= 2
- interviews with `clinical_domain_gap = 2` >= 2
- paid or grant-backed PoC paths >= 1

A small sample is `INCOMPLETE`, not a failure. A sufficiently large sample that misses one or more substantive thresholds is `FAIL` and narrows the product.

## R0 gate

The base R0 gate requires:

- synthetic/public-only evidence;
- no real patient data;
- >=100 base cases;
- S0 current IPU baseline;
- S1 generic PII baseline;
- S3 bounded B63 hybrid R0 prototype;
- passing benchmark tests;
- measured clinical utility;
- reproducibility metadata;
- no catastrophic recall collapse for a pass candidate.

### R0-A audit hardening

The independent audit of IPU Draft PR #103 found that a co-designed synthetic corpus can make contextual metrics look stronger than they are. Therefore `PASS_CANDIDATE` also requires all of the following evidence:

- a frozen independent holdout with >=30 base cases;
- unseen holdout templates;
- unseen holdout lexical values/synonyms where applicable;
- S3 rules frozen before holdout evaluation;
- the holdout itself shows measurable advantage;
- synthetic identifier fixtures are collision-safe / provably non-real test values;
- synthetic-identifier safety tests pass;
- changed-file or bounded benchmark-tree secret scan passes;
- the benchmark is executed as exact-head evidence;
- the evaluated tree is clean (`git_dirty = false`).

The >=30 holdout threshold is a provisional R0-A validation threshold, not a regulatory sample-size claim.

Verbatim clinical-utility retention remains an allowed R0 measurement level, but it must not be described as downstream clinical utility. `utility_measurement_level` makes that distinction explicit.

An explicit `NARROW`, `STOP_OR_REFRAME`, or `INCOMPLETE` from the R0 implementation is preserved rather than overwritten by a weighted score.

## Final decision

```text
customer PASS + hardened R0 PASS -> PASS_CANDIDATE
any required evidence missing    -> INCOMPLETE
customer FAIL                    -> NARROW
R0 NARROW                        -> NARROW
R0 STOP_OR_REFRAME               -> STOP_OR_REFRAME
real patient data used           -> STOP_OR_REFRAME
```

`PASS_CANDIDATE` never means full build is authorized. The output always includes:

```json
"full_build_authorized": false
```

Owner/CTO review remains required before any runtime work.

## CLI

```bash
node scripts/b63-validation-gate.mjs \
  customer-evidence.json \
  r0-result.json
```

Optional third argument overrides the gate configuration path.

Exit behavior:

- `0`: valid evidence evaluated;
- `2`: malformed/invalid evidence;
- `3`: real-patient-data / synthetic-only boundary violation.

## Tests

```bash
node --test scripts/b63-validation-gate.test.mjs
```

The tool intentionally uses only built-in Node.js APIs and adds no package dependency.

Audit-hardening coverage includes:

- independent holdout required;
- synthetic identifier collision safety required;
- changed-file secret scan required;
- clean exact-head benchmark evidence required;
- weak/negative holdout result cannot be promoted to PASS.
