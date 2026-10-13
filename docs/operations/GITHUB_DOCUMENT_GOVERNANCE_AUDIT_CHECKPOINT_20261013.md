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
