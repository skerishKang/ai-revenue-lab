# GitHub document governance audit — checkpoint 01 (2026-10-13)

> **Purpose:** Resume a bounded, evidence-based examination of existing public GitHub docs without relying on the chat's memory window. This is an audit worklog/manifest, **not** the private company business policy and **not** an authorization to change any product strategy.
>
> **Repository:** `skerishKang/ai-revenue-lab` (public). **Immutable source baseline:** `main 5476d1038993d647bf8ba241ce6a4307cccf291f`. GitHub recursive tree response: `truncated=false`.

## 1. Exact audit accounting

- Repository blobs: **5,963**.
- Recognized document blobs: **835** = 798 Markdown, 18 text, 17 PDF, 2 DOCX.
- Root distribution: `docs/` 400; `reference/` 253; `apps/` 150; `packages/` 19; other paths 13.
- Full frozen path/blob-SHA/size/read-state inventory: [GITHUB_DOCUMENT_AUDIT_MANIFEST_20261013.tsv](GITHUB_DOCUMENT_AUDIT_MANIFEST_20261013.tsv).
- **Read-state cursor:** `TEXT_SAMPLED=125`; `INDEXED_ONLY=691`; `BINARY_PENDING=19`. `TEXT_SAMPLED` means some or all source text has been fetched and inspected; **not** all 125 have undergone complete line-by-line business-policy classification. `INDEXED_ONLY` means content **has not** been read. Do not promote this checkpoint to “835 documents reviewed”.
- The 46 `reference/business-*/README.md` files in the sampled set demonstrate broad Business coverage, **not** full inspection of their sibling docs.
- A path may belong to a historical, proposed, externally succeeded, or technical-only product. **Never infer active business status from a directory label.**

## 1A. Batch 02 — 25 additional full-document reads (2026-10-13)

**Latest inspection progress (same frozen 835-document baseline):**
- Original checkpoint: 125 text-sampled, 691 indexed-only, 19 PDF/DOCX pending.
- After Batch 02: **150 documents have at least some text inspection** (125 prior samples + **25 additional full-document fetches and content triages**); **666 remain indexed-only**; **19 binaries remain text-uninspected**.
- Batch 02 is recorded in [the exact-source 25-file audit report](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH02_20261013.md) with per-file business ID, historical/current-evidence marker and public/mixed/business-review triage.
- The [835-file manifest](GITHUB_DOCUMENT_AUDIT_MANIFEST_20261013.tsv) now marks each of these 25 as `TEXT_FULL_FETCHED_B02`; their original blob hashes remain unchanged.
- **Not a completion claim:** old 125 text samples were not upgraded to full reviews; the 25 newly examined documents remain *provisional* classifications pending any actual migration judgment. No PDF/DOCX, GitHub Issues/PRs, local business policy, local document inventory, production, or customer file was modified.
- **Important review distinction:** business-content candidates inside B35 and B05 are not a reason to relocate adjacent technical render/QA/architecture files automatically.

## 1B. Batch 03 — another 25 full-document reads (2026-10-13)

**Latest progress on the frozen 835-file baseline:** **175 text-inspected at least partly** (125 initial samples; 25 Batch 02 full-text triages; 25 Batch 03 full-text triages), **641 path-only/unread**, **19 PDF/DOCX binaries unread**.

- [Batch 03 audit and 25 source-specific provisional verdicts](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH03_20261013.md)
- [Updated 835-file manifest and per-file reading cursor](GITHUB_DOCUMENT_AUDIT_MANIFEST_20261013.tsv)
- Batch 03 reviewed B53 Sidecar, B54 Claw, B64 Reward Router, B66 Quote, B14, B60 and other Business product/technical source contracts.
- High-priority business-content follow-up: B53 commercialization, B54 historic pilot material, B64 owner launch sequence, B66 customer storage policy, historic B02/B03 price hypotheses. **No current business decision or new customer requirement was established here.**
- Keep public technical evidence and protected runtime status facts intact. No local Governance relocation, original-file edit, GitHub Issue/PR cleanup or production mutation was made.

The original `## 1. Exact audit accounting` numbers remain **the 2026-10-13 initial snapshot**, not an updated final count; this section and the manifest supply the most recent cursor.

## 1C. Batch 04 — complete-source review of 25 further documents (2026-10-13)

Latest frozen-manifest cursor: **200 text-inspected at least partly** (125 initial samples + 25 each in B02, B03 and B04); **616 unread index-only**; **19 PDF/DOCX binaries pending**.

- [Batch 04 exact-source document classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH04_20261013.md).
- B53 shared-runtime/host technical boundary; B54 redacted pilot discovery versus customer technical controls; B14 dated provider-resource limits; central model S0/S1/S2/S3 chronology; canonical four shared Internal Platform components.
- **No current business pricing, operating mode, customer entitlement, retention, or policy authority was adopted**; proposal dates must be reconciled against latest Owner decisions. No local Governance inspection or source relocation.
- All 25 paths have unchanged baseline blob SHA, and all 25 new statuses are `TEXT_FULL_FETCHED_B04` only.

## 1D. Batch 05 — another 25 exact-source full-text inspections (2026-10-13)

**Latest status:** 225 documents with at least some inspected text: 125 initial samples + 25 each B02/B03/B04/B05; 591 still path-only/unread, and 19 original PDF/DOCX binaries still pending.

- [Batch 05 per-file review with pinned path/blob SHAs](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH05_20261013.md).
- B66 Google Drive/customer-storage evidence versus unactivated certified native Sol PDF; B54 Claw PC read-only access versus real command/user approval; B14 historical 11-model/provider API/dated free quota and early BYOK pilot runbooks.
- No current pricing, customer promise, model entitlement, connector activation, data-retention period or business direction approved.
- No local Governance changes, source document relocation, customer data copy, redaction/history rewrite, or production mutation.

## 1E. Batch 06 — 25 additional full-source reads plus B35 sampled-source spot review (2026-10-13)

**Current cumulative frozen-manifest cursor:** **250** documents text-inspected at least in part (125 original `TEXT_SAMPLED` + 25 each B02/B03/B04/B05/B06); **566** indexed-only documents still unread; **19** original PDF/DOCX bodies pending. The five already sampled B35 commercial sources additionally spot-reviewed in Batch 06 are **not counted a second time**.

- [Batch 06 pinned file-by-file classifications and B35 non-counted sampled-source reconciliation](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH06_20261013.md)
- Core findings: B35 internal commercial drafts and unapproved contract assumptions must not be promoted into binding price/business policy; B35 design/QA remains separable public technical evidence. B05 historical resident priority; B21/B51 synthetic research/product references; B60 dated editorial directions; cross-product tier preferences are owner evaluation, not customer activation.
- No private commercial clauses, customer identifying data or pricing figures were reproduced in the public audit. No source docs, Governance, CI/code, cloud runtime, secrets, Git history or product policy were mutated.

## 1F. Batch 07 — 25 additional full-document reads (2026-10-13)

Latest frozen 835-source cursor: **275 documents with at least some text viewed** (125 initial samples + 25 each B02/B03/B04/B05/B06/B07), **541 indexed-only text bodies unread**, **19 PDF/DOCX bodies pending**. Existing 125 text samples are not asserted fully reviewed.

- [Batch 07 source-pinned 25-file report and classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH07_20261013.md).
- B54 external connector source contracts and SMS/Kakao commercial/provider-selection seams; B60 field-level official-source review/publication; B57/B58 rights and synthetic consent; B59 immutable source reader; B29 apartment product-not-company Governance; B39/40/41 nonlive emergency references; B49 public-data provenance.
- No current legal/commercial customer rights, subscription pricing, live connector activation, emergency-service affiliation, model use or company-wide governance decided. Original content and local Governance unchanged.

## 1G. Batch 08 — 25 additional exact-source full-text reads (2026-10-13)

Latest fixed 835-item cursor: **300 documents with text viewed at least partly** (125 early samples + B02/B03/B04/B05/B06/B07/B08 25 each), **516 `INDEXED_ONLY` unread**, **19 PDF/DOCX binary bodies pending**. Original `TEXT_SAMPLED` 125 still require line/section-level review.

- [Batch 08 pinned 25-source triage, Git blob proof and temporal authority distinctions](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH08_20261013.md)
- Canonical shared IP-CORE/ENGINE/CONTROL/SIDECAR technical owners are not a newly invented company-wide Business or a second duplicate common-platform folder. Historical model counts, owner-run S1, old 30/40/45-second caps and first-revenue/MVP source hypotheses must not override subsequent B14/Agent policies or real operational evidence.
- Stable technical security/resource protection, product entitlement independence and exact provider native-model routing remain untouched. No business policy/adoption/public remediation decisions made.

## 1H. Batch 09 — 25 full source reads (2026-10-13)

**Current frozen original cursor:** **325** documents with text seen at least partially (125 initial sampled + 25 each B02/B03/B04/B05/B06/B07/B08/B09), **491 indexed-only text bodies unread**, **19 PDF/DOCX binary bodies pending**. Initial 125 still require explicit full-document section coverage.

- [Batch 09 source-pinned 25-file B14 model evaluation and B54 Claw authority review](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH09_20261013.md).
- B14 historical provider one-shot connectivity, temporary free routes, Owner account eligibility and native parameter corrections stay separate from present provider costs, per-product tier grants or Engine/Claw/B66 E2E. No provider calls or model-state changes.
- B54 canonical pairing and resident execution/security contracts stay in public technical sources. Connection Center M0 and historic source integration status do not prove actual remote control, SaaS commercial promise or live production authority.
- Original business docs remain untouched; no local Governance migration, product policy, Cloudflare state or Git history mutation.

## 1I. Batch 10 — 25 more complete-source reads (2026-10-13)

Latest frozen 835-item cursor: **350 source documents with text read at least partly** (125 original `TEXT_SAMPLED` plus 25 each B02–B10); **466 `INDEXED_ONLY`** full text bodies not read; **19 PDF/DOCX original binary bodies pending**. The first 125 remain only sampled, not certified fully audited.

- [Batch 10 pinned B14/ModelScope/Kira and B54 Cloud/OSS/Neon/Windows connector findings](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH10_20261013.md).
- Dated ModelScope 504, Kira limited promotion/subscription and partial Sol PDF trials are not current model eligibility, plan pricing or certified customer E2E. Cloud hosting vendor comparisons and OSS licensing must be separated from technical threat models and actual paid/contractual commitments.
- No original public source editing, company-Governance migration, credential/provider API calls, local machine access, business-policy activation or Cloudflare mutation.

## 1J. Batch 11 — 25 additional complete-source reads (2026-10-13)

Latest immutable **835**-source cursor: **375 documents whose text was seen at least partly** (125 original samples + 25 each B02/B03/B04/B05/B06/B07/B08/B09/B10/B11), **441 `INDEXED_ONLY` unread**, **19 PDF/DOCX binary bodies pending**. The 125 initial `TEXT_SAMPLED` records still require complete classification.

- [Batch 11 pinned #3580 Hark Office, Drive, Telegram, WEB-FIRST P01 and local transport audit](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH11_20261013.md).
- Product priority: owner-dated WEB-FIRST intake vs explicitly chosen Windows fallback; do not conflate product roadmap with a new shared architecture.
- Drive READ != WRITE; Telegram READ != SEND; metadata/source selection != P01 approval != exact-run Resident execution != artifact delivery; code/source and synthetic E2E must not be described as current live authority.
- No original docs/credentials/customer files/local Governance/product policies changed. No production or live provider mutations.

## 1K. Batch 12 — 25 complete-text reads (2026-10-13)

Frozen 835 original document cursor after B12: **400 source texts viewed at least partially** (125 initial samples + 25 each B02–B12); **416 index-only text unread**, **19 PDF/DOCX binary bodies pending**. All original early 125 `TEXT_SAMPLED` retain their separate, not-fully-classified status.

- [Batch 12 pinned Hark/Claw #3580/#3929/#3933/#3936 exact source triage](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH12_20261013.md).
- Important product distinction: 2026-10-11 WEB-FIRST owner priority and optional Windows Excel fallback; separately verified P01 READ and WRITE/edit and supported *standard quote summary PDF*, **not** arbitrary faithful Excel print reproduction.
- Historical Engine caller app allowlist HTTP 409 and source remedy are *dated evidence*, not a current Production readiness conclusion; read-only Cloudflare binding snapshots likewise dated.
- No original documents moved/edited, no local Governance touched, no customer file/provider writes/model or production modifications.

## 1L. Batch 13 — 25 B54 activation / B16 B18 B19 B53 product reference documents (2026-10-13)

Frozen 835-original-document cursor: **425 documents with text viewed at least partly** (125 `TEXT_SAMPLED` + 25 each B02–B13), **391 `INDEXED_ONLY`** unread text, **19 BINARY_PENDING** unread PDF/DOCX. Initial 125 need separate deeper whole-document classification.

- [Batch 13 SHA-pinned 25-document governance audit](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH13_20261013.md)
- B54 public ingress/Owner P01 SSE direction and independent PADIEM-vs-B66 customer policies remain distinct from actual deployed/runtime permissions.
- B16 sports, B18 audio, B19 family memory and B53 embedded SDK are synthetic/static editorial/product research, not current real customer data, media rights, SaaS pricing, released SDK or live provider activation.
- No original file/Git history, local Governance, customer data, secrets, connector, Cloudflare or production configuration changed.

## 1M. Batch 14 — 25 source reads: operations rules and B14/B13/B02/Portfolio (2026-10-13)

**Fixed original 835 inventory:** **450 documents with some text read** (125 original sampled + 25 each B02–B14); **366 index-only unread**, **19 original PDF/DOCX pending**. Initial `TEXT_SAMPLED` 125 still require independent complete reading/classification.

- [Batch14 exact-source SHA catalog and provisional Governance-vs-technical findings](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH14_20261013.md).
- Canonical code quality, CI, minimum relevant checks, operator rollback and UI proofs are engineering controls; owner machine/Docker preferences are operational owner records, not company commercial policy.
- B14 earlier BYOK 30-second limitations are historical, later native model caps preserve security resource limits; B13 media rights, B02 live provider/PII and owner-only Portfolio Console business metrics require separate commercial/privacy decisions.
- Source SHA preservation only, no original file changes, off-Git Governance, secrets, live service changes or customer data.

## 2. Candidate reading queues; no relocation or final determination yet

| Queue | Confirmed source locations | Why read next | Classification state |
| --- | --- | --- | --- |
| Common portfolio business authority | `docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`, `docs/vision/PROJECT_VISION.md`, `docs/decisions/ADR-0001-first-revenue-experiment.md`, `docs/product/PRODUCT_PORTFOLIO.md` | Historical/present business theses and prioritization may be mixed into product/development narratives | **Candidate; owner authority and validity not reconciled** |
| B14 direction and provider commercialization | `apps/korean-ai-platform/docs/BUSINESS14_DECISION_LOG.md`, `apps/korean-ai-platform/docs/API_PROVIDER_PHASE0_CHARTER.md`, `apps/korean-ai-platform/docs/PHASE1_BYOK_GATEWAY_CHARTER.md` | Business assumptions and technical implementation stages mixed; dated decisions may be superseded | **Candidate; historical vs current not decided** |
| B35 commercial packet | `docs/commercial/business-35-ai-media-education-dx/`, `docs/operations/business-35/` | Multiple existing documents explicitly label themselves internal commercial drafts; package includes customer proposal/PDF/DOCX | **High review priority; content relocation not authorized by this report** |
| B54 Claw packaging and product direction | `apps/korean-ai-code-agent/docs/07_BUSINESS_PRICING.md`, `apps/korean-ai-code-agent/docs/01_PRODUCT_CHARTER_AND_PRD.md`, `docs/product/B54_CLAW_CONNECT_DESKTOP_DUAL_SURFACE_PRODUCT_PLAN_20261010.md` | Business packaging vs technical access and deployment contracts may be mixed | **Candidate; do not adopt dated pricing as current** |
| B60 product/editorial operations | `docs/portfolio/BUSINESS_60_AI_API_PROPOSAL.md`, `reference/business-60-ai-api-v1/operations/B60_EDITORIAL_OPERATIONS.md` | Product business assumptions and implementation/editorial procedures need distinct roles | **Candidate; owner decision needed for ambiguous lines** |
| B66 product/customer operations | `docs/products/b66/README.md`, `docs/products/b66/CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md` | Customer process and source/runtime acceptance may overlap | **Candidate; preserve technical source truth** |
| Historic/proposed Business-specific choices | `reference/business-05-neighbor-market-v2/PRODUCT_DECISION.md` and remaining `reference/business-*/` files | Business-level promises/differentiation may appear in static UX reference contracts; not all are active | **Per-Business review pending** |

This table contains only **existing publicly visible file paths and neutral inspection reasons**. Do **not** paste extracted private policy text or confidential client/commercial decisions into this audit.

## 3. Source documents that remain development-side authorities unless Owner directs otherwise

- `docs/portfolio/BUSINESS_REGISTRY.md` — business numbering and technical ownership registry; not equivalent to the private business policy.
- `docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md` — historical/external implementation relationships; verify before treating a legacy Business as current.
- `docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md` — **GitHub documentation status/precedence**, not the confidential company's Governance folder itself.
- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` — engineering/CI/deployment execution rules, subject to the separate business authority.
- `AGENTS.md` — **public path and read-first precedence** pointing to the local Governance directory.

Business-specific screens and technical product specifications can remain in GitHub. **No rule says an entire file must move merely because it contains the word Business, Owner, policy, or decision.** Mixed files need line-by-line separation before any edits.

## 4. Next checkpoint protocol (small slices)

1. Select a bounded batch of source files from the `INDEXED_ONLY` pool, prioritizing explicit commercial/strategy/decision material. Keep its baseline Git blob SHA.
2. Actually read the relevant **full text**, including headings, current-vs-historical markers and references. For binaries, inspect text separately; do not mark reviewed by filename.
3. For each candidate record: `source path`, `blob SHA`, `Business ID or COMMON/UNKNOWN`, `technical/public vs mixed vs business-policy candidate`, `active/historical/ambiguous`, `owner-question-needed`, and `next action proposed`. Classification is an *audit proposal* until the Owner resolves material ambiguity.
4. Record the batch verdict in a dated follow-on checkpoint and adjust the manifest cursor. **Do not reclassify a public product contract as private merely from a title.**
5. Check today's `main` drift against the frozen manifest before future changes. Already examined files that changed SHA require selective re-review.
6. Until the Owner directs another phase: **no local file relocation, no deletion/rewrite of historical Git, no production/code change, no creation of one Governance folder per proposed Business by assumption**.

## 5. Confidentiality / memory safeguards

The real internal business policy is maintained **outside this Git repository**. Only the approved local path and read instructions are in root [AGENTS.md](../../AGENTS.md). This public checkpoint holds **source references, read states and action candidates only**. Chat memory cannot be treated as the official audit ledger: the manifest + checkpoint commit provides durable resumability.

**Checkpoint complete means:** all 835 paths counted and the already-fetched text sources recorded. **Checkpoint does not mean:** substantive classification of all documents, archival review of all GitHub issues/PRs, PDF/DOCX reading, privacy assessment or approved movement of files.
