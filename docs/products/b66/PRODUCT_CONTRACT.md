# B66 Product Contract

~~~text
DOC_STATUS = CURRENT_PRODUCT
OWNER = B66 product
PARENT = #3389
~~~

## Product promise

The primary B66 customer is an existing business with a quotation document it already uses.

B66 should let that business:

1. register an existing quotation as source evidence;
2. review what B66 learned;
3. see a reproduction generated from the learned template;
4. compare that reproduction with the source/reference PDF;
5. approve the template, including any explicitly accepted deviations;
6. create later quotations by supplying only new business facts.

Convenience does not authorize a silent fidelity downgrade. B66 must first attempt and measure faithful reproduction. A user may explicitly accept a known visual difference when the workflow benefit is more important to them.

## Product concepts

### Saved Quote Skill

The user-facing reusable capability: "내 견적서". It owns or references business defaults, variable input schema, document behavior, QuoteCore binding, approved private assets and the approved internal rendering template.

### Canonical Quote Template

Lifecycle-level term for the analyzed, deterministic visual/render contract used by certification and execution. The current implementation may represent this with QuoteTemplateProfile plus private assets, print/render rules, slot mappings and provenance. This document does not require a source-code type rename.

### Quote Instance

One actual quotation created from a certified template and a particular set of new facts.

### QuoteCore

Sole deterministic authority for quotation arithmetic and approved business calculations. A renderer or spreadsheet output must not become a competing calculation engine.

## Runtime separation

One-time onboarding may be comparatively expensive:

~~~text
source
-> analysis
-> Canonical Quote Template candidate
-> reproduction
-> reference comparison
-> certification
~~~

Repeat generation is latency-critical:

~~~text
user request
-> bounded fact interpretation
-> QuoteCore
-> Certified Canonical Quote Template
-> fast deterministic renderer
-> Preview / PDF
~~~

~~~text
ONE_TIME_LEARNING_COST = ACCEPTABLE
REPEAT_GENERATION_LATENCY = CRITICAL
SOURCE_REANALYSIS_PER_REPEAT = 0
STRUCTURED_TEMPLATE_RENDER_MODEL_CALLS = 0
~~~

Editable formats are optional output compilers:

~~~text
Certified Canonical Quote Instance
  ├-> fast Preview/PDF renderer
  ├-> clean XLSX compiler
  ├-> Google Sheet compiler
  └-> future supported formats
~~~

Excel/OneDrive, Google Sheets, HanCell or another office engine must not be placed on the critical PDF path merely because it can open a source workbook. Renderer choice is subordinate to measured certification quality and runtime cost.

## Execution eligibility

~~~text
EXECUTION_ALLOWED
IFF
TEMPLATE_CERTIFICATION_STATUS in {
  CERTIFIED,
  CERTIFIED_WITH_TOLERANCE
}
~~~

CERTIFIED_WITH_TOLERANCE requires explicit user/owner review of known deviations. New source-derived templates must not become executable merely because analysis succeeded.

## Shared authority

B66 remains a standalone product but reuses approved shared authorities for identity, storage/Drive, AI execution and document semantics where applicable.

It must not create a second Padiem account/session authority, duplicate QuoteCore math, create a product-local provider/model registry, or create an unreviewed second generic document parser authority.

## Preview and final artifact

The product must avoid two independently laid-out representations of the same quotation. A certified renderer should use either one canonical page representation for both preview and PDF, or the final generated PDF itself as the preview artifact/projection.

The preview may scale the whole page for display, but it must not silently alter internal layout rules.
