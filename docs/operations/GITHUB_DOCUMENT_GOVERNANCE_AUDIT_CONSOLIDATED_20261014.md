# PADIEM GitHub original-document governance audit — Batch 36 consolidated triage (2026-10-14 KST)

> **Scope:** 835 recognized original files (798 MD, 18 TXT, 17 PDF, 2 DOCX) at immutable original Git tree `5476d1038993d647bf8ba241ce6a4307cccf291f`. Cross-batch B02–B35 reports and the frozen [835-source manifest](GITHUB_DOCUMENT_AUDIT_MANIFEST_20261013.tsv) are the evidence, not current `main` feature-readiness or private corporate Governance. See the [complete exact-source classification register](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_CLASSIFICATION_REGISTER_20261014.tsv).

## Consolidation outcome and exact reconciliation checks

Every reported source classification was matched to a **single** path in the frozen manifest and compared against its immutable original Git blob SHA, original byte size and final review state.

- **Original source rows:** 835; unique classified original paths 835; unclassified 0; duplicate paths 0; paths absent from manifest 0; frozen blob SHA/size/state mismatches 0.
- **Report coverage:** B02–B28, 25 new originals each; B29, 16; B30, 19 PDF/DOCX; B31–B35, 25 each. **B06's 5 extra B35 sample re-inspections do not add source rows** and were omitted from the original-row numerator; those source paths are classified from their final full-source review batch.
- **Reading coverage:** 816 text originals fully inspected plus 19 PDF/DOCX bodies inspected = 835; no `TEXT_SAMPLED`, `INDEXED_ONLY` or `BINARY_PENDING`.
- **No original source content or metadata changed.** This phase created an independent classification registry. The existing manifest is left unchanged.

| Provisional class | Number | Interpretation — not automatic publication clearance |
| --- | ---: | --- |
| `TECH_PUBLIC` | **376** | Repository technical design, code-adjacent documentation and verification records; re-use allowed only within actual source/security/license boundaries |
| `PRODUCT_PUBLIC` | **166** | Public-safe product scope, visual/UI/UX references and synthetic demos; not an owner-approved release, actual customer acceptance or rights certification |
| `TECH_OWNER_RECORD` | **137** | Technical operation decisions, Owner development-authority chronology, security/release gates and status records; current runtime proof must be independently checked |
| `MIXED_REVIEW` | **126** | Technical material combined with business priorities, prospective commercial rules or Owner scope; needs section-level separation before any disclosure/move |
| `BUSINESS_REVIEW` | **30** | Commercial proposals, pricing, sales strategy, pilot outreach, historical revenue/portfolio decisions or Owner business-policy candidates; status is not proof of current adopted policy |
| **TOTAL** | **835** | **All provisional** |

**Baseline business-governance screen:** 126 mixed + 30 business = **156 original documents**. In addition, some files of other classes warrant explicit privacy/rights review, even when a technical narrative is otherwise publicly reviewable.

## Independent follow-up queues in the 835-row register

These mutually exclusive queue labels are an **operating triage convenience**, not legal judgments. High-priority disclosure/rights gates override the provisional primary class.

| Follow-up queue | Rows | Meaning / bounded next action |
| --- | ---: | --- |
| `PRIVACY_CRITICAL_OWNER` | **2** | Two already-committed B66 CGI reference PDFs with identical blob SHA and apparent real business/individual/contact/financial fields; Owner plus security/privacy/legal must decide public-exposure containment. **No values recopied here.** |
| `IDENTITY_CONSENT_OWNER` | **6** | Named real-world B29 community/council visual references: verify individual identity, consent scope and what may stay public |
| `CUSTOMER_COMMERCIAL_OWNER` | **20** | B35 commercial/package source documents combining proposed customer offer, draft terms and implementation; review permitted publication and agreement authority |
| `PROVIDER_OFFER_OWNER` | **4** | B60 opportunity-promotion editorial/product directions require verified source rights, accurate current provider offers and Owner alignment |
| `COPYRIGHT_CHECK` | **3** | Selected B57 literary-source/translation notes; confirm source rights and publication scope rather than assuming protected modern translations are free |
| `BUSINESS_OWNER` | **17** | Other business-only commercial strategy, tariff, sales/pilot, number and prioritization records awaiting Owner authority |
| `MIXED_OWNER_REVIEW` | **111** | Other mixed business/technical source requiring bounded section-level separation; do not rewrite/move whole document blindly |
| `TECH_PRODUCT_CONTRACT_ONLY` | **672** | No special high-priority business/privacy gate found during this provisional triage. Technical product/runtime/license/freshness verification still applies |
| **TOTAL** | **835** | **163 follow-up rows** across the first seven specialized queues; does not itself establish 163 unique secrets or privacy infringements |

The category count (156) and the specialized queue count (163) answer **different questions** and must not be added together. Queues are one-per-row, prioritizing disclosure risk even when a source's dominant category is technical.

## Owner decisions to request, without disclosing the underlying values

| Priority | Decision ID | Decision Owner should make | Explicitly not done by this audit |
| --- | --- | --- | --- |
| **P0** | DG-01 | Authorize a security/privacy/legal handling plan for the two B66 CGI reference PDFs; determine legitimate public-use rights, required restriction/remediation and whether Git history is implicated | No public reproduction of personal/contact/financial fields; no delete, redaction, repo visibility or history rewrite |
| **P1** | DG-02 | Confirm B29 named community/council publicity permission and any required de-identification or release restrictions | No private individual/household record copied |
| **P1** | DG-03 | Identify which B35 offer, customer package, fee/delivery/contract and retention terms are approved company commitments versus proposal drafts | No contract/customer pack issued; no rate card adopted |
| **P1** | DG-04 | Resolve first-generation company strategy, B05 successor commerce/ranking and subscription/product tiers as present business authority or history only | No company policy changed; no duplicate source workspace |
| **P2** | DG-05 | Confirm B60 provider-offer editorial direction and external claim/image/terms licensing; preserve B14 execution-provider authority separately | No offer published, provider contacted, model or route enabled |
| **P2** | DG-06 | Check translation/source licensing and other remaining mixed-record excerpts for publication/re-use compatibility | No copyright/legal clearance conferred |
| **P2** | DG-07 | Choose retention/separation strategy for approved technical evidence vs confidential business decision records and future delta scans | No local Governance content accessed/moved or new shared Governance/platform folder created |

**Private decision-record rule:** This public summary contains *only topic codes and minimum safe referents*. Actual unpublished terms, personal identity details, financial account values, draft negotiation language and detailed Owner deliberation must be recorded **only in an authorized non-public channel/location** if and when supplied and approved. Nothing in this report represents such a private document as already created.

## Handling rules and evidence limits

1. **Public technical work stays technical.** IP-CORE / IP-ENGINE / IP-CONTROL / IP-SIDECAR, B14 model execution, B54 Claw, B62 Chat and B66 Quote have existing source-of-truth technical/product boundaries. Do not create a second common platform, Governance package or model approval ledger.
2. **Do not infer runtime rights from a document.** Owner model selection, provider registration, account/product entitlement, deployed binding, customer production E2E and successful visual acceptance require distinct recent evidence.
3. **Do not promote dated business hypotheses to company decisions.** Original vision, pricing, marketing, historical partner proposals, sample tier models and customer package draft clauses require current Owner authority.
4. **Do not expose or destroy originals.** This is a public-safe *classification* and routing index only. No source relocation/removal, redaction, local-file copy, original blob edit, cloud/runtime change, customer data view or Git rewrite was undertaken.
5. **The frozen-scope limit is explicit.** This register covers exactly 835 originals at a historical Git revision; new/changed material added after the freeze requires separate current-`main` delta comparison and classification, not silent inclusion in the 835 denominator.

## Completion verdict

**B36 immutable original-source classification: COMPLETE (835/835)**. **Owner business decisions, disclosure remediation, private file reorganization, and post-freeze `main` delta audit: OPEN / NOT EXECUTED.**

The classifications and seven decision topics above are ready for Owner review; they are neither authorization to publish all 542 `TECH_PUBLIC`/`PRODUCT_PUBLIC` sources to a new audience nor a claim that existing public-looking records are safe from real-world privacy, confidential-business or licensed-source concerns.
