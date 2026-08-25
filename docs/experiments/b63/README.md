# B63 Validation Evidence

B63 is a **proposed** Business number for the Korean Clinical AI Egress Control Plane hypothesis. This directory contains validation contracts only.

Files:

- `validation-gates.json` — versioned gate thresholds and issue authority.
- `customer-discovery.schema.json` — editor/tool schema for interview evidence.
- `r0-result.schema.json` — editor/tool schema for technical R0 evidence.
- `customer-discovery.example.json` — synthetic example; not interview evidence.
- `r0-result.example.json` — synthetic example; not benchmark evidence.

R0 `PASS_CANDIDATE` is intentionally stricter than a benchmark's own mechanical verdict. It requires independent holdout evidence, collision-safe synthetic identifiers, explicit secret-scan evidence, and clean exact-head benchmark execution. These controls were added after the independent audit of IPU Draft PR #103.

No file here authorizes a runtime workspace, claims clinical validation, or permits real patient data.
