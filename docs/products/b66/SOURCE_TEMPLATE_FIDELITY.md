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

Technical capabilities described here (not an upload allowlist):

- source-document analysis on supported PDF/XLSX/HWPX paths, only where the relevant intake/parser has been separately enabled;
- page/layout reproduction;
- fonts, spacing, baselines and wrapping;
- table/vector geometry;
- logo/stamp/image geometry, transparency and layering;
- source-derived template compilation;
- mutation of bounded variable slots while preserving unchanged regions;
- reference-PDF comparison.

This is **not** a general software-development model-ranking policy and is not a B14 runtime model-routing policy.

**Technical analysis scope does not grant customer template-registration
permission.** Under #3586 and the [B66 product entrypoint](README.md), the
current reusable-template allowlist is **XLSX = ACCEPT**, **HWPX = FUTURE**,
**XLS/HWP = REJECT**. PDF/DOCX/PPTX/images may be handled by separately
supported intake or reference-comparison paths, but this document does not
make them accepted reusable-template registration formats.

## 2. Lifecycle

The product-level lifecycle is owned by the [B66 product entrypoint](README.md).
This document contains the **technical stage gates**, not a second independent
definition of the product flow.

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

Only a certified template enters normal repeat generation. The authoritative
Saved Quote Skill -> QuoteDraft -> QuoteCore -> certified-template -> Preview/PDF
product flow is maintained in [README.md](README.md). The following are
**fidelity-specific execution gates**:

```text
SOURCE_DOCUMENT_REQUIRED_AT_REPEAT_RUNTIME = NO
SOURCE_REANALYSIS_PER_REPEAT = 0
CERTIFICATION_PER_QUOTE = 0
QUOTECORE_CALCULATION_AUTHORITY = YES
STRUCTURED_TEMPLATE_RENDER_MODEL_CALLS = 0
```

Once certified, PDF output is produced by executing the verified deterministic
renderer/converter, not by asking an AI model to recreate the page layout.
This applies to the certified PDF-native path; any separately approved
HTML-to-PDF path likewise runs existing conversion code without model
inference. Model reasoning can assist source analysis, initial implementation
or debugging, but is **not** a repeat-PDF rendering dependency.

Material changes to renderer geometry, typography/font resolution, page behavior, asset placement/alpha/layering, table structure or wrapping require certification applicability review.

## 4. Reference authority

For an explicitly supported source-derived template, the mechanically
inspectable source is design evidence, and the reference PDF is the visual
oracle. This distinction does **not** expand the customer template
registration allowlist (#3586):

```text
SUPPORTED_SOURCE_DOCUMENT
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
PRODUCTION_VERIFICATION_SCOPE = SOURCE_ONLY
```

Separately, the latest recorded authorized CGI Production browser E2E
(run 37741635545; see #3751 and #3733) passed login, assigned Saved Quote
Skill, Guided QuoteCore values, certified preview, and an actual downloaded
browser PDF. Complete Freeform interpretation failed with HTTP 502 classified
as upstream_timeout (one POST, zero retry/fallback); Partial Freeform/follow-up
was not tested. The exact model selected and timeout origin were not proven.
This is **run-specific historical Production evidence**, not proof that the
current served revision passes end-to-end.

```text
PRODUCTION_GUIDED_BROWSER_PREVIEW_AND_PDF = PASS_ON_RECORDED_RUN
PRODUCTION_COMPLETE_FREEFORM = HTTP_502_UPSTREAM_TIMEOUT
PRODUCTION_PARTIAL_FOLLOWUP = NOT_TESTED
CUSTOMER_READY = NO
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

GENERIC_ANALYZER_COMPILER = PROVEN
SECOND_UNRELATED_TEMPLATE = CERTIFIED
SECOND_UNRELATED_TEMPLATE_REQUIRED = SATISFIED
```

The generic analyzer/compiler derives every slot binding from source-derived observation —
label-anchored semantic roles, geometric item-table and totals detection, XLSX provenance
binding and calendar-date serial resolution — instead of the CGI compiler's hardcoded
`K4/K5/K7/K9`, `B13`, `E/F/G 14..16`, `G22:G24`, `C23`, `A11` and `CAMERA_Y_MAX=275`.

Proof (issue #3628, PR #3630): a materially different second quotation — landscape page,
left-aligned header field block, gapped item columns, `[소계]/[V.A.T]/[총계]` totals wording,
no camera object, 80 vs 23 source sheet merges — was driven through source -> analysis ->
compiled Canonical Template -> reference facts -> deterministic renderer -> reproduction PDF ->
certification by the same generic code path:

```text
BASELINE_BYTE_IDENTICAL = YES
CRITICAL_FIDELITY_GATES = 14/14 PASS
RASTER_SIMILARITY = 0/0/0 (72/150/300 dpi)
MUTATION_CASES = 14  PASS = 11  REJECTED = 3  FAIL = 0
MAX_OUTSIDE_ALLOWED_CHANGED_PIXELS = 0
CGI_SPECIFIC_LITERAL_IN_GENERIC_COMPILER = 0
CUSTOMER_PRIVATE_FACT_IN_GENERIC_ENGINE = 0
```

The generic pipeline lives in `tools/b66_generic/`; private customer source is never committed
(only hashes, gate results and a public-safe synthetic fixture). Executing a template that has
not been certified remains denied: the product path refuses unapproved bundles and tampered
fingerprints before the renderer is reached.

## 6. Renderer selection

Renderer choice is subordinate to evidence.

Historical candidates included HTML/Chromium, Google Sheets, native workbook/Excel/Graph, HanCell and other approaches. These experiments remain useful evidence but are not current product authority.

A slower editable-document compiler may remain an optional output path while a faster certified renderer handles Preview/PDF.

## 7. Golden-method rule

When a difficult document problem is solved, preserve the reusable method as:

- architecture note;
- reference implementation;
- automated validator;
- critical-element gates;
- negative/rejection tests;
- root-cause evidence.

The goal is to reuse a proven solution instead of rediscovering and revalidating the same method repeatedly.

## 8. Historical issue map

These issues remain evidence but are no longer competing authorities for current CGI renderer direction:

- #3545 — CGI fidelity implementation evidence;
- #3574 — HTML V3 / one canonical A4 DOM experiment;
- #3578 — native-workbook/renderer bake-off;
- #3581 — Google Drive/Sheets renderer experiment;
- #3584 — Google-native asset/camera normalization experiment.

Current decisions should be read from this document plus #3542/#3595, not reconstructed by combining older experiment threads.
