# B66 · Padiem Quote

```text
DOC_STATUS = CANONICAL_PRODUCT_ENTRYPOINT
OWNER = B66 product
PRODUCT_EPIC = #3180
SOURCE_ANALYSIS_AUTHORITY = #3542
REPRODUCTION_CERTIFICATION_AUTHORITY = #3595
SOURCE_FORMAT_POLICY = #3586
```

B66 is Padiem's standalone quotation product for businesses that already have quotation formats they use repeatedly.

The user-facing reusable concept is **내 견적서 / Saved Quote Skill**. Internal template/profile/compiler terminology is not the primary user concept.

## Canonical product flow

```text
existing quotation
-> source analysis
-> Canonical Quote Template candidate
-> reference reproduction
-> certification
-> approved Saved Quote Skill
-> repeat quote execution with new facts
```

Routine repeat use must be fast and deterministic:

```text
new facts
-> Saved Quote Skill
-> QuoteDraft
-> QuoteCore
-> certified template
-> Preview / PDF
```

QuoteCore remains the sole calculation authority. The renderer does not become a second money/tax/date calculation engine.

## Current authority map

| Area | Current authority | Status meaning |
|---|---|---|
| Product / Saved Quote Skill | #3180 | overall product epic |
| Source analysis | #3542 | source facts -> ANALYZED candidate |
| Reproduction / certification / compiler generalization | #3595 | pre-execution fidelity gate; generic compiler proven on a second unrelated template |
| Template registration source formats | #3586 | XLSX now; HWPX future; legacy XLS/HWP rejected |
| Quote shell / single composer UX | #3536 | product UX |
| Native XLSX output | #3496 | optional editable output; not PDF critical path |

Historical renderer experiments are evidence, not current authority: #3545, #3574, #3578, #3581 and #3584.

## Current CGI result

The CGI reference quotation has reached a certified template result inside its declared scope:

```text
CGI_REFERENCE_TEMPLATE = CERTIFIED
GENERIC_RUNTIME_RENDERER = YES
CGI_TEMPLATE_REUSABLE = YES
GENERIC_ANALYZER_COMPILER = PROVEN
SECOND_UNRELATED_TEMPLATE = CERTIFIED
SOURCE_PRODUCT_INTEGRATION = MERGED
PRODUCT_INTEGRATION = PRODUCTION_ACTIVATION_PENDING
```

The runtime renderer consumes compiled template data without CGI/customer literals, and the
generic analyzer/compiler no longer carries CGI-specific source/cell structure: a materially
different second quotation (landscape, left-aligned header block, gapped item columns,
`[소계]/[V.A.T]/[총계]` totals, no camera object, 80 vs 23 source merges) was compiled and
certified by the same generic code path with no document-specific cell/path literal
(`tools/b66_generic/`, with evidence under `tools/b66_generic/evidence/`). The authenticated
Saved Quote Skill -> QuoteCore -> certified PDF download path is source-integration validated;
customer handoff is not complete until the reviewed private CGI bundle is provisioned and the
Production account path passes authenticated E2E.

## Source formats: intake capability vs template-registration policy

Lower-level file intake/parser capability and B66 template registration are different contracts.

```text
GENERIC_INTAKE_CAPABILITY
!=
B66_TEMPLATE_REGISTRATION_ALLOWLIST
```

The current template-registration policy is:

```text
XLSX = ACCEPT
HWPX = FUTURE
XLS = REJECT
HWP = REJECT
```

PDF/DOCX/PPTX and images may still be accepted by other bounded intake/extraction paths where the product explicitly supports them. That does not automatically make them authoritative source formats for registering a reusable B66 quotation template.

## Preview / PDF / editable outputs

A certified fast PDF path is the critical repeat-generation path. Editable XLSX/Google Sheet output is optional and may be generated separately.

Do not insert Excel, Google Sheets, HanCell or another office engine into every PDF request merely because it can open the source format.

## Canonical documentation

- [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md) — source analysis, reproduction, certification, PDF/image fidelity implementation, current CGI architecture and development-model operating guidance.
- This README — product boundary, current authority map and current status.

Implementation/demo references such as `reference/business-66-padiem-quote-v1/` remain useful source/evidence, but they are not the canonical B66 product-policy authority.
