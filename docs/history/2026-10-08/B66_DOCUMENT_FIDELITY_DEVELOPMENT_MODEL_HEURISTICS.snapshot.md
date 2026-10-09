# B66 document/image-fidelity development-model guidance — historical snapshot

```text
DOCUMENT_STATUS = HISTORICAL_ARCHIVE
CURRENT_OPERATING_POLICY = NO
CURRENT_B14_OR_B66_MODEL_ROUTING_AUTHORITY = NO
SOURCE_DOCUMENT = docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md
SNAPSHOT_BASE_MAIN = e784c9c5f60fd04698b8ccd994ad74c4e39efd23
```

This is the preserved original Section 7, recording **past developer experiments
and model-selection heuristics**, not current owner-approved B14/B66 runtime
model routing, paid/free price policy, or fidelity certification requirements.
Current authority belongs to the
[owner model policy](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)
and [B66 fidelity contract](../../products/b66/SOURCE_TEMPLATE_FIDELITY.md).
The original historical content follows unchanged.

---

## 7. Development-model operating guidance — document/image fidelity only

This section records an **empirical development workflow** from the B66 document-fidelity work. It does not define a global coding-model hierarchy and does not change B14/provider/runtime routing.

```text
DEVELOPMENT_WORKFLOW_ONLY = YES
GENERAL_CODING_POLICY = NO
PRODUCT_RUNTIME_MODEL_ROUTING = NO
```

### When the document/image fidelity problem is new

Use a premium high-reasoning model first when:

- the correct renderer/representation is unknown;
- several technically plausible rendering paths exist;
- root cause is visual/PDF-internal rather than a simple code defect;
- fidelity is blocked by layout, font, graphics-state, alpha/layering or document-format semantics.

Current operational shorthand:

```text
GPT-class premium lane
-> one-pass-first architecture / golden-method discovery
```

This is a preference, not a guarantee.

### When a golden method already exists or premium capacity is unavailable

Use GLM/other free or low-cost models with review-assisted multi-pass execution.

```text
PASS 1
-> implementation

CENTRAL review
-> classify measured failures
-> give invariants / experiments, not merely "try again"

PASS 2+
-> root-cause correction
-> rerun the same gates
```

Current empirical interpretation from CGI:

```text
GPT-class result
= reached the successful PDF-native solution class quickly

GLM 5.3 Flash
= weaker first pass
  but reached a comparable CGI final result after bounded review/correction
```

Do **not** generalize this into "GPT always succeeds once" or "GLM always succeeds twice." It is only an operating heuristic for source-derived document/image fidelity work.

Escalate from the low-cost lane when the same failure class repeats after two reviewed passes without material progress, or when a new solution class is clearly required.

### Cost decision

For these fidelity tasks, evaluate:

```text
EFFECTIVE_COST
=
MODEL_COST
+ ITERATION_TIME
+ HUMAN_REVIEW_TIME
+ FAILURE_RISK
```

A free model is not operationally cheaper when repeated attempts consume more critical-path time than one premium pass. Conversely, once a golden method and validator exist, low-cost models are appropriate for repeated implementations and bounded corrections.
