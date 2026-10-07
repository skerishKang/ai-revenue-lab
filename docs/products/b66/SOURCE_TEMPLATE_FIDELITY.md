# B66 · Source Template & Document Fidelity Contract

```text
DOC_STATUS = CANONICAL_PRODUCT
OWNER = B66 product
ANALYSIS_AUTHORITY = #3542
CERTIFICATION_AUTHORITY = #3595
SCOPE = source-derived quotation templates, document/image fidelity implementation and certification
```

## 1. Scope

This contract applies when B66 learns or reproduces an existing quotation document and must preserve its visual/document behavior.

Typical scope:

- PDF/XLSX/HWPX source analysis;
- page/layout reproduction;
- fonts, spacing, baselines and wrapping;
- table/vector geometry;
- logo/stamp/image geometry, transparency and layering;
- source-derived template compilation;
- mutation of bounded variable slots while preserving unchanged regions;
- reference-PDF comparison.

This is **not** a general software-development model-ranking policy and is not a B14 runtime model-routing policy.

## 2. Lifecycle

```text
SOURCE
  -> ANALYSIS
  -> Canonical Quote Template candidate
  -> REPRODUCTION
  -> CERTIFICATION
  -> CERTIFIED | CERTIFIED_WITH_TOLERANCE | REJECTED
  -> EXECUTION
```

### ANALYSIS

#3542 owns source analysis.

Analysis records what is actually present and classifies facts as:

```text
OBSERVED_SOURCE_FACT
DERIVED_MAPPING
MANUAL_APPROXIMATION
UNKNOWN_UNSUPPORTED
```

Analysis answers: **Did B66 understand the source?**

ANALYZED alone does not authorize repeat execution.

### REPRODUCTION

Render the reference/sample business facts from the compiled candidate.

```text
Canonical Quote Template candidate
+ reference facts
-> deterministic renderer
-> reproduction PDF
```

Reproduction answers: **Can B66 rebuild the source from what it learned?**

### CERTIFICATION

#3595 owns certification and execution eligibility.

Review at minimum when material to the source:

- page size/orientation/print area/margins/scale;
- section/table/cell geometry;
- text position and clipping;
- font family/weight/size;
- glyph width, spacing, baseline and line-height;
- wrap/shrink-to-fit/overflow behavior;
- borders/fills/vector rules;
- logo geometry;
- stamp geometry, alpha and layering;
- reference-value parity;
- whole-page and important-region raster similarity;
- bounded mutation robustness.

A favorable aggregate visual-diff score does not waive a material visible defect.

```text
CERTIFIED
= declared-scope structural/visual gates pass
  + representative mutations preserve document behavior

CERTIFIED_WITH_TOLERANCE
= a known deviation remains
  + user/owner explicitly reviewed and accepted it

REJECTED
= normal repeat execution denied
```

Silent tolerance is forbidden.

## 3. Execution contract

Only a certified template enters normal repeat generation.

```text
new user facts
-> approved Saved Quote Skill
-> QuoteDraft
-> QuoteCore
-> certified Canonical Quote Template
-> deterministic Preview / PDF
```

```text
SOURCE_DOCUMENT_REQUIRED_AT_REPEAT_RUNTIME = NO
SOURCE_REANALYSIS_PER_REPEAT = 0
CERTIFICATION_PER_QUOTE = 0
QUOTECORE_CALCULATION_AUTHORITY = YES
STRUCTURED_TEMPLATE_RENDER_MODEL_CALLS = 0
```

Material changes to renderer geometry, typography/font resolution, page behavior, asset placement/alpha/layering, table structure or wrapping require certification applicability review.

## 4. Reference authority

For a source-derived template:

```text
SOURCE_XLSX/HWPX/etc.
= structural/design evidence where mechanically inspectable

REFERENCE_PDF
= visual acceptance oracle
```

The reference PDF detects renderer-specific differences. It does not overwrite mechanically observed source facts.

## 5. CGI reference architecture — current result

The CGI work established a stronger PDF-native approach after earlier HTML/office-renderer experiments.

Current accepted architecture:

```text
reference PDF
-> immutable vector base document

source analysis
-> compiled semantic mutable slots

repeat quote values
-> QuoteCore
-> generic runtime renderer
-> isolated Form-XObject overlay for changed slots
-> final PDF
```

The reference-reproduction benchmark keeps the original PDF content stream
unchanged and overlays replacement content. The customer-facing product
integration adds one bounded safety step before the same overlay: text inside
the **changed compiled slot covers only** is removed so superseded customer
values are not left searchable/copyable beneath the visual replacement.
Images and line art are not redacted. A no-op render still returns the
reference PDF byte-for-byte.

This product-integration hardening changes the internal content stream for a
mutated document, so it does **not** inherit the benchmark's content-stream
identity claim. It must instead be re-certified against all of the following:

```text
BASELINE_BYTE_IDENTICAL = YES
CHANGED_SLOT_STALE_TEXT = 0
MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS = 0
COMPILED_FONT_RESOURCE_MATCH = YES
```

Current independently rechecked CGI evidence:

```text
BASELINE_BYTE_IDENTICAL = YES
MUPDF_72_150_300_CHANGED_PIXELS = 0/0/0
PDFIUM_72_150_300_CHANGED_PIXELS = 0/0/0
MUTATION_CASES = 12/12 PASS
MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS = 0
REJECTION_CASES = 4/4 PASS
RUNTIME_CGI_LITERAL = 0
```

Current source-only product-integration recertification on the actual local
Cloudflare workerd / Pyodide path additionally records:

```text
WORKER_PYMUPDF = 1.26.3
WORKER_MUTATION_CASES = 12/12 PASS
WORKER_REJECTION_CASES = 4/4 PASS
MUPDF_PDFIUM_DPI_MUTATION_CHECKS = 72/72 PASS
MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS = 0
CHANGED_SLOT_STALE_TEXT_CHECKS = 51/51 PASS
COMPILED_FONT_RESOURCE_CHECKS = 63/63 PASS
RUNTIME_CGI_LITERAL = 0
MAX_TEST_PDF_BYTES = 20047904
FULL_PRODUCT_WRANGLER_DRY_RUN = PASS
PRODUCTION_ACTIVATION = PENDING
```

The Worker integration is independently re-certified rather than automatically
inheriting the CPython/PyMuPDF 1.26.4 benchmark result. The private bundle is
bound to the approved Saved Quote Skill/profile fingerprints, renderer source
hash and engine version; a renderer change therefore invalidates the old
bundle instead of silently reusing it.

The prior camera leak was not a camera-scale defect. Direct content-stream mutation changed interpretation of existing graphics state. Isolated overlay removed the outside-region leak without a camera-scale constant.

### Generality boundary

```text
GENERIC_RUNTIME_RENDERER = YES
CGI_TEMPLATE_REUSABLE = YES

GENERIC_ANALYZER_COMPILER = UNPROVEN
SECOND_UNRELATED_TEMPLATE_REQUIRED = YES
```

The current compiler still knows CGI-specific source/cell structure. A materially different second quotation must prove that source analysis/compiler logic can create the same class of certified template without document-specific hardcoding.

## 6. Renderer selection

Renderer choice is subordinate to evidence.

Historical candidates included HTML/Chromium, Google Sheets, native workbook/Excel/Graph, HanCell and other approaches. These experiments remain useful evidence but are not current product authority.

A slower editable-document compiler may remain an optional output path while a faster certified renderer handles Preview/PDF.

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

## 8. Golden-method rule

When a difficult document problem is solved, preserve the reusable method as:

- architecture note;
- reference implementation;
- automated validator;
- critical-element gates;
- negative/rejection tests;
- root-cause evidence.

The goal is not to pay the premium model for the same discovery repeatedly.

## 9. Historical issue map

These issues remain evidence but are no longer competing authorities for current CGI renderer direction:

- #3545 — CGI fidelity implementation evidence;
- #3574 — HTML V3 / one canonical A4 DOM experiment;
- #3578 — native-workbook/renderer bake-off;
- #3581 — Google Drive/Sheets renderer experiment;
- #3584 — Google-native asset/camera normalization experiment.

Current decisions should be read from this document plus #3542/#3595, not reconstructed by combining older experiment threads.
