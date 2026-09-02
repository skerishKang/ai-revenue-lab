# B35 Authority and Artifact Matrix

This matrix is the startup classification for Issue #1502. W0 must fresh-check every row and may refine status without changing the governing rules.

| Item | Current authority | Startup status | Reuse policy | Owning workstream |
|---|---|---|---|---|
| B35 product identity / promise | merged main V3.1, PR #370 | authoritative | preserve | W0 / parent |
| `PRODUCT_CONTRACT.md` | merged main V3.1 | authoritative | preserve | W0 / parent |
| V3.1 reference UI | merged main | authoritative product evidence | do not redesign by default | outside closeout lanes |
| PR #355 `CURRENT_PRODUCT_AUTHORITY.md` | Draft lineage | useful bridge | reconcile to fresh main | W1 #1503 |
| PR #355 README | Draft lineage | useful source | reconcile | W1 #1503 |
| One-page offer source | PR #355 | reusable, must verify V3.1 alignment | adapt | W1 #1503 |
| Ten-page proposal source | PR #355 | reusable, must verify V3.1 alignment | adapt | W1 #1503 |
| Diagnostic questionnaire source | PR #355 | reusable | preserve useful questions, align terminology | W1 #1503 |
| Six-week pilot plan | PR #355 | reusable | preserve as delivery plan, not product identity | W1 #1503 |
| SOW draft | PR #355 | reusable | adapt only to current offer/scope | W1 #1503 |
| Risk/data annex | PR #355 | reusable | preserve concrete controls, remove stale claims | W1 #1503 |
| KPI framework | PR #355 | reusable | preserve measurable definitions, no invented results | W1 #1503 |
| Qualification scorecard | PR #355 | reusable | preserve if current customer segment fits | W1 #1503 |
| Customer-package generation scripts | PR #359 | reusable engineering asset | selectively recover / reconcile | W2 #1504 |
| Master Proposal PPTX/PDF | PR #359 | historical pre-V3.1 binary | regenerate; do not send | W2 #1504 |
| One Page Offer source/PDF | PR #359 | historical pre-V3.1 binary | regenerate | W2 #1504 |
| Diagnostic Questionnaire DOCX/PDF | PR #359 | historical binary | regenerate from accepted current source | W2 #1504 |
| Pilot Quote Template XLSX | PR #359 | reusable structure, content/formulas require fresh validation | regenerate/verify | W2 #1504 + W3 #1505 |
| Customer Meeting Script | PR #359 | reusable text asset | align to V3.1 | W2 #1504 |
| Follow-up Email Templates | PR #359 | reusable text asset | align to V3.1, no send | W2 #1504 |
| Source mapping / customization checklist | PR #359 | reusable QA/ops asset | reconcile | W2 #1504 |
| Structural/formula validators | PR #359 | reusable engineering asset | independently audit and strengthen | W3 #1505 |
| Rendered page/sheet evidence | PR #359 | historical | regenerate for exact current package | W2/W4 |
| Old pixel QA verdicts | PR #359 | historical only | never reuse as current PASS | W4 #1507 |
| Customer-specific recipient/company facts | none in reusable master | unresolved by design | insert only in named-customer finalization | W5 #1508 |
| Final named-customer price | price hypotheses only | unresolved by design | explicit customer-specific approval | W5 #1508 |
| Legal/contract review completion | not established by closeout | unresolved by design | separate factual gate | W5 #1508 |
| Customer send authorization | not authorized | blocked | separate explicit owner action | post-closeout |

## Authority precedence

```text
fresh merged main product contract
> accepted closeout commercial source
> accepted regeneration manifest and outputs
> legacy Draft source/binaries
> old rendered/QA evidence
```

## Stale-evidence rule

A previous validator PASS, screenshot, pixel review, formula result or binary hash does not transfer to a regenerated artifact. Every material output revision requires fresh evidence.

## Customer-specific rule

The reusable master package is not required to contain final recipient identity, negotiated price or customer-specific contract language. Those belong to the named-customer activation gate, not to the reusable-master completion gate.
