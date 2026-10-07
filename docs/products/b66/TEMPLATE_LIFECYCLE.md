# B66 Source-Derived Template Lifecycle

~~~text
DOC_STATUS = CANONICAL_PRODUCT
OWNER = B66 product
ANALYSIS_ISSUE = #3542
REPRODUCTION_CERTIFICATION_ISSUE = #3595
~~~

## Decision

A source-derived B66 quotation template passes four distinct stages:

~~~text
SOURCE
  ↓
ANALYSIS
  ↓
Canonical Quote Template candidate
  ↓
REPRODUCTION
  ↓
reference-data reproduction PDF
  ↓
CERTIFICATION
  ↓
CERTIFIED | CERTIFIED_WITH_TOLERANCE | REJECTED
  ↓
EXECUTION
~~~

Analysis and reproduction are not interchangeable. Analysis asks whether B66 understood the source. Reproduction asks whether B66 can rebuild the source document from what it learned. Certification asks whether that template is reliable enough for future quotations. Execution applies new user facts only after certification.

## Stage 0 — source evidence

Accepted product formats are governed separately by the B66 template-registration allowlist. The current spreadsheet policy is .xlsx; future .hwpx may be supported. Legacy engineering samples may still be inspected without becoming user-facing intake formats.

For mechanically inspectable sources:

~~~text
SOURCE_DOCUMENT
= structure/design authority for extractable facts

REFERENCE_PDF
= visual acceptance oracle
~~~

The reference PDF does not replace source facts. It reveals renderer-specific differences such as glyph metrics, baseline, line-height, print scaling, asset geometry and application rendering behavior. The original source remains immutable evidence.

## Stage 1 — analysis

Authority: #3542.

The analysis record classifies facts as OBSERVED_SOURCE_FACT, DERIVED_MAPPING, MANUAL_APPROXIMATION or UNKNOWN_UNSUPPORTED. It inventories structure, values needed to understand behavior, typography, geometry, print/page settings, reusable assets and special objects.

The output state is ANALYZED. ANALYZED does not authorize normal quote execution.

## Canonical Quote Template candidate

The lifecycle concept includes the deterministic visual/render contract required to reproduce the quotation. It may contain/reference section/cell/table geometry, row/column dimensions and merges, typography and text behavior, fills/borders/alignment, page and print settings, asset geometry/layering, source provenance, variable slot mapping, approved private asset refs, renderer/compiler metadata, and linkage to the Saved Quote Skill and QuoteCore.

The existing internal QuoteTemplateProfile remains a valid implementation carrier.

## Stage 2 — reproduction

Use the reference/sample facts from the source, not new user mutations.

~~~text
Canonical Quote Template candidate
+ reference facts
-> deterministic renderer
-> reproduction PDF
~~~

The purpose is to isolate rendering fidelity from natural-language interpretation and changed business values. A template that cannot materially reproduce its own reference is not execution-ready.

## Stage 3 — certification

Certification compares the reproduction PDF to the reference PDF using [REPRODUCTION_CERTIFICATION.md](REPRODUCTION_CERTIFICATION.md).

~~~text
CERTIFIED
CERTIFIED_WITH_TOLERANCE
REJECTED
~~~

Known deviations are not silently converted into success.

~~~text
SYSTEM_ASSUMED_TOLERANCE = NO
USER_REVIEWED_TOLERANCE = YES
SILENT_FIDELITY_DOWNGRADE = NO
~~~

After baseline fidelity, bounded mutation-robustness checks ensure realistic value changes do not break layout semantics.

## Stage 4 — execution

Only a certified template enters the normal quote-generation path.

~~~text
new user facts
-> approved Saved Quote Skill
-> QuoteDraft
-> QuoteCore
-> certified Canonical Quote Template
-> deterministic output
~~~

~~~text
SOURCE_DOCUMENT_REQUIRED_AT_RUNTIME = NO
SOURCE_REANALYSIS_PER_REPEAT = 0
REPRODUCTION_CERTIFICATION_PER_QUOTE = 0
QUOTECORE_CALCULATION_AUTHORITY = YES
~~~

Natural-language interpretation may extract new variable facts under the existing B66 contract. It does not become layout or arithmetic authority.

## Material template revisions

A change that can affect certified visual behavior requires applicability review. Re-certify affected claims when a change touches geometry, typography/font resolution, print/page behavior, asset placement/alpha/layering, wrap/shrink logic, table structure or renderer implementation.

Unrelated repository drift does not automatically invalidate template certification.

## Historical boundary

The lifecycle is forward-looking. Historical handoff records such as #3521 are not rewritten or reopened merely because a stronger certification model is adopted later.
