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
| Reproduction / certification / compiler generalization | #3595 | source certification/generalization proven (including a second unrelated template); parent issue #3595 remains OPEN for tracking disposition |
| Template registration source formats | #3586 | XLSX now; HWPX future; legacy XLS/HWP rejected |
| Quote shell / single composer UX | #3536 | product UX |
| Native XLSX output | #3496 | optional editable output; not PDF critical path |
| B66 quote-model decision authority | [Single model authority index](../../models/README.md), [Owner approval policy §0A](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), #3760 | **Owner policy corrected and merged (#3796):** user selects one exact registered, allowed, ready B14 model per run; optional visible/replaceable default only if configured; no free/paid filter, backend automatic selection or fallback. Matching B66 UI/API implementation remains Draft #3831 and is not Production active. |

Historical renderer experiments are evidence, not current authority: #3545, #3574, #3578, #3581 and #3584.

## Shared platform and release rules

The quotation workflow, QuoteCore calculations and template certification remain B66-specific responsibilities. The common [architecture and ownership index](../../common/README.md) provides shared platform boundaries, and the [development lifecycle index](../../lifecycle/README.md) points to the repository-wide validation, approval and deployment contracts. Neither link changes the current customer readiness or permits a Production release.

## Model decision versus executable runtime

The **current Owner decision** is an authenticated user's one exact, registered, Owner-allowed and runtime-ready B14 model per quote interpretation. An optional default is only a visible editable preselection, never a hidden picker. An absent, invalid, excluded or unavailable `model_id` fails closed; no automatic free-first choice, ranking, retries or fallback. This stable contract is owned by the [canonical Owner policy](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), not this B66 README.

**Status is split:** the Owner policy (#3796) and B14 single-JSON registry consolidation (#3819) are **MERGED**. B66 manual UI/API choice is still Draft (#3831). The older combined #3836 is **pre-merge integration test evidence only**, not a fresh current-main proof or a merge candidate. Model registration/configured credential and protected customer Production E2E remain separate acceptance gates. Historical free-first code on main must not be advertised as satisfying today's per-request user choice.

## Current CGI result

The CGI reference quotation has reached a certified template result inside its declared scope:

```text
CGI_REFERENCE_TEMPLATE = CERTIFIED
GENERIC_RUNTIME_RENDERER = YES
CGI_TEMPLATE_REUSABLE = YES
GENERIC_ANALYZER_COMPILER = PROVEN
SECOND_UNRELATED_TEMPLATE = CERTIFIED
SOURCE_PRODUCT_INTEGRATION = MERGED
PRODUCTION_GUIDED_BROWSER_PREVIEW_AND_PDF = PASS
PRODUCTION_COMPLETE_FREEFORM = HTTP_502_UPSTREAM_TIMEOUT
PRODUCTION_PARTIAL_FOLLOWUP = NOT_TESTED
CUSTOMER_READY = NO
```

The runtime renderer consumes compiled template data without CGI/customer literals, and the
generic analyzer/compiler no longer carries CGI-specific source/cell structure: a materially
different second quotation (landscape, left-aligned header block, gapped item columns,
`[소계]/[V.A.T]/[총계]` totals, no camera object, 80 vs 23 source merges) was compiled and
certified by the same generic code path with no document-specific cell/path literal
(`tools/b66_generic/`, with evidence under `tools/b66_generic/evidence/`). The authenticated
Saved Quote Skill -> QuoteCore -> certified PDF download path is source-integration validated.

The latest recorded authorized CGI Production browser E2E passed login, the assigned Saved
Quote Skill, Guided QuoteCore entry/calculation, certified preview and an actual downloaded
browser PDF. The first Complete Freeform interpretation instead returned HTTP 502 classified
as upstream_timeout on one POST, with no retry/fallback; Partial Freeform/follow-up was not
reached. The exact selected model and timeout origin were not proven. These are
run-specific Production observations, not proof that the current deployed revision passes
all customer scenarios. The full CGI customer handoff remains incomplete (CUSTOMER_READY=NO).
See #3751 and #3733 for the protected-run evidence and remaining acceptance gates.

The separate source certification/generalization evidence is PROVEN, but its parent
tracking issue #3595 is still OPEN; the proof result must not be confused with the
GitHub issue's closure state.

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
- [Model decision and runtime evidence index](../../models/README.md) — unified entrypoint to the Owner policy, actual B14 catalog, product route declarations and deployment evidence. The canonical B66 Owner policy correction was **merged in PR #3796**; the historical automatic free-first implementation remains a source-level discrepancy until [Draft PR #3831](https://github.com/skerishKang/ai-revenue-lab/pull/3831) is independently reviewed and merged. [#3819](https://github.com/skerishKang/ai-revenue-lab/pull/3819) has now **MERGED** the B14 JSON registry; [#3836](https://github.com/skerishKang/ai-revenue-lab/pull/3836) is earlier integration CI proof only and MUST NOT be merged as a substitute. No model/provider activation or customer E2E is claimed.

Implementation/demo references such as `reference/business-66-padiem-quote-v1/` remain useful source/evidence, but they are not the canonical B66 product-policy authority.
