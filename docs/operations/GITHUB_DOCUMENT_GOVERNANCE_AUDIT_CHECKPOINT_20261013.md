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

## 1O. Batch 15 — 25 full-source reads (2026-10-13)

Frozen original inventory: 835. **475** documents have text viewed at least partly (125 initial samples + 25 each B02–B15), **341** remain INDEXED_ONLY and **19** PDF/DOCX are BINARY_PENDING. Initial 125 sampled entries still require deep review.

- [Batch 15 original-SHA-indexed classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH15_20261013.md).
- Editorial/hosting hypotheses, proposed institutional validation, provider benchmark rights and pricing require independent current owner/legal review. Synthetic family and story reference art has no customer data rights.
- Shared Chat/Claw copy does not prove actual service activation; no original files, local private Governance, provider routes or production state changed.

## 1P. Batch 16 — 25 source reads: B20/B22/B33/B34/B36/B37 and B58 rights (2026-10-13)

Frozen original 835-document cursor: **500** documents with some text inspected (125 early `TEXT_SAMPLED` + 25 each B02–B16), **316** index-only unread, and **19** PDF/DOCX binary unread. Initial 125 require full reading and category decisions.

- [Batch 16 25 source SHA-pinned business/technical/reference classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH16_20261013.md)
- Keep memory facts separate from fiction, media source from synthetic derivative, research annotations from verified citations, actual voice/translation rights from simulated studio UI.
- B36 safety coordination and B37 route visual references cannot be described as emergency dispatch, real navigation, crime scoring or guaranteed protection; substantive safety service and personal data policy decisions remain separate.
- Only audit records updated; no original docs, private Governance files, customer information, live service or provider/Cloudflare settings changed.

## 1Q. Batch 17 — 25 additional exact-source reads (2026-10-13)

Immutable original 835-document cursor: **525 with text viewed at least partly** (125 original samples + 25 each B02–B17); **291 INDEXED_ONLY unread** text; **19 BINARY_PENDING** PDF/DOCX. The original 125 sampled sources remain pending complete classification.

- [Batch17 public-safe SHA-pinned review of B45/B46/B48/B51/B55/B57 and B52](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH17_20261013.md).
- B45 content source-rights and human review do not authorize publication; B46 actual personalization requires consent; B48 exact version independent proof is not a generic release grant.
- B51 listing/reference validation does not install or charge workflows; B55 fleet plan does not execute Claw tasks; B57 original vs modern translation/editorial edition rights require independent clearance; B52 schedule concept not running.
- No source modification, live deployment, real customer/provider data, off-Git Governance access or new model/business policy.

## 1R. Batch 18 — 25 source reads: B14/B62/B66/P01 activation and operator controls (2026-10-13)

Original 835-document cursor: **550 with text viewed at least partly** (125 initially sampled + 25 each B02–B18), **266 INDEXED_ONLY** text unread, **19 BINARY_PENDING** PDF/DOCX unread. Initial 125 samples still need independently complete classification.

- [Batch 18 SHA-pinned per-source audit and owner/technical split](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH18_20261013.md).
- Dated B14 provider/tier experiments, Atria/Agnes error diagnostics and one-off provider comparisons are not current model availability, membership or charged-call authority. Distinguish B62 search-transport proof from actual reply E2E.
- Corporate Dothome account backup/deletion requires Owner review; P01 capability promotions, Source and Preview do not grant new customer Agent permissions; Tabbit UI QuickCheck is not a substitute for contract/security CI.
- No original source/Git history, private off-Git Governance, customer material, provider account, subscription or deployment changed.

## 1S. Batch 19 — 25 UI/UX portfolio source reads (2026-10-13)

Frozen 835-document cursor: **575** source texts at least partly inspected (125 early `TEXT_SAMPLED` + B02–B19 25 each); **241** INDEXED_ONLY bodies not read; **19** original PDF/DOCX BINARY_PENDING. Initial 125 samples still require exhaustive classification.

- [Batch19 SHA-pinned visual owner/process and B02–B32 product direction audit](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH19_20261013.md).
- Historical `OWNER_UI_APPROVED=false`, frozen `KEEP`/redo directions and automated screenshot references are not current owner approval; B06 method is reusable, not one dark palette for every Business.
- B09 minors, B13 media rights and B17 merchant voice/scene materials require independent owner/rights/privacy decisions. B29 Apartment Governance and B32 Skill Studio retain protected product-specific review authority, not off-Git corporate Governance.
- Original sources and SHA/size, business decisions, customer files, live products, local private Governance and deployment remain untouched.

## 1T. Batch 20 — 25 complete-source reads: B33–B59 visual direction / B47 and B59 reference evidence (2026-10-13)

Frozen original **835** document cursor: **600 source documents with some text inspected** (125 early `TEXT_SAMPLED` + 25 each B02–B20), **216 INDEXED_ONLY** unread text bodies and **19 BINARY_PENDING** unread PDF/DOCX original bodies. Initial 125 sampled originals remain pending exhaustive classification.

- [Batch20 SHA-pinned source and provisional public-safe governance classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH20_20261013.md).
- B33/B34 review authorities must not be overwritten by portfolio visual redesign. B36–B41 prototypes do not connect to real emergency, medical or navigation services and human decisions remain final.
- B44 Cloudflare security challenge is not product screenshot proof. B46 real profiling, B57 translation copyrights and B58 writing voice permissions require separate Owner/legal decisions. B51/52/53/55/59 concepts are not live installs, automations, SDKs, fleet or OCR/PDF production.
- No original source modification, off-Git Governance access, customer/provider data, business authorization, protected branch merge or live deployment.

## 1U. Batch 21 — 25 source reads: Model evidence and core platform/product contracts (2026-10-13)

At fixed **835** originals: **625 texts partly or completely viewed** (125 original sampled, 25 each B02–B21), **191 INDEXED_ONLY text unread**, **19 BINARY_PENDING PDF/DOCX unread**. The 125 early sampled documents still need independent exhaustive review.

- [Batch21 SHA-pinned original model, Core/Engine/Control, copyright and B61/B67 triage](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH21_20261013.md).
- One historical model provider error/free quota does not set current Free/Plus/Pro/Max or authorize charged calls; Core/Engine/Control/B14 retain distinct technical authority and source-vs-live obligations.
- Keep MIT/OFL license notices; pypdf decoder disabled pending provenance; B61 Bible mapping demands exact source rights/verse provenance. B66 synthetic quote fixture and approved PDF template are not current customer acceptance.
- No original source history, local private Governance, commercial membership, customer data, live Provider or Production changes.

## 1V. Batch 22 — 25 complete text reads: CI economy / CTO accountability / historical HWPX (2026-10-13)

Frozen original 835-document cursor: **650 sources viewed partly or completely** (125 initial `TEXT_SAMPLED`, 25 each B02–B22); **166 INDEXED_ONLY** original text bodies unread, **19 BINARY_PENDING** PDF/DOCX unread. First sampled 125 need exhaustive later review.

- [Batch22 SHA-pinned 25-record public-safe engineering-vs-business classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH22_20261013.md)
- GitHub Actions concurrency/skip/prewarm changes are technical CI optimization, not waiver of security, true runtime probes, exact-head merge checks or Owner approval. Cancelled, skipped and historic results must not be equated with current PASS.
- CTO/developer/independent validator forms define separation of duties; old HWPX Draft and September ownership snapshots are not current product or company business authority.
- No CI source, original Git documents, local Governance, customer data, commercial policy, paid provider or Cloudflare Production changed.

## 1W. Batch 23 — 25 source reads: signup/rewards/B66, OSS image/PDF, desktop and platform integration (2026-10-13)

Frozen 835-original cursor: **675 at least partly text-reviewed** (125 initial `TEXT_SAMPLED` + 25 each B02–B23); **141 INDEXED_ONLY** unread text originals and **19 BINARY_PENDING** original PDF/DOCX unread. The initial 125 sampled files still require full review.

- [Batch23 exact-source SHA audit and business/engineering separations](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH23_20261013.md).
- Shared OTP, DanjiOn/customer contact, B64 reward providers, B14 shared-free terms, B66 product administrator access, Living Learning membership and B60 asset rights retain separate commercial/customer decisions.
- Pillow/pypdf supply chain, desktop withdrawal, third-party license notices, Sidecar and CI optimizations are bounded technical controls; none prove live service or permission to bypass security.
- No original file, source/hash/size, local corporate Governance, customer data, vendor/provider account, actual product policy or deployment changed.

## 1X. Batch 24 — 25 full-text source reads: CTO forms, B02 Living Travel, B01 Personal Edition and B13 Video Archive (2026-10-13)

Frozen original 835-document cursor: **700 source documents with text viewed at least partly** (125 early `TEXT_SAMPLED` + 25 each B02–B24); **116 INDEXED_ONLY** text bodies unread; **19 BINARY_PENDING** PDF/DOCX unread. Initial 125 samples still require exhaustive re-review.

- [Batch24 exact-source SHA-pinned public-safe business/technical triage](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH24_20261013.md)
- Historical Living Travel July staging pass is not later V2 design Owner approval or today's live service; July Personal Edition visual QA success does not reverse V2 owner rejection and V3 hold.
- Third-party Pexels derivatives, real YouTube IDs/thumbnails and personal video journal need separate content rights/consumer privacy decisions; static previews and localhost screenshot locators cannot certify Production availability.
- No original source modifications, commercial Owner-policy adoption, local corporate Governance access, real provider/customer data, rejected product PR merge, or production deployment.

## 1Y. Batch 25 — 25 full original source reviews: B06/B07/B10/B11/B12/B15 rights, image, motion and test evidence (2026-10-13)

Frozen **835 original** cursor: **725 documents seen at least in part** (125 initial `TEXT_SAMPLED` + 25 each B02–B25); **91 INDEXED_ONLY** original text unread and **19 BINARY_PENDING** original PDF/DOCX unread. Original sampled 125 still require exhaustive category review.

- [Batch25 SHA-pinned original public-safe classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH25_20261013.md).
- B06 World Feed and B07 meaning atlas use synthetic assets and animation, not actual current stories, private memories or user tracking. B10 fictional fan magazine is no real-person likeness grant and an external binary evidence manifest is not the binary itself.
- B11 annotated source reading doesn't own genuine copyrighted lessons and isn't B04 adaptive teaching; B12 editorial relay isn't live CMS/content generation. B15 newsroom mock doesn't fact-check or publish real claims without external source/legal and human editorial authority.
- No original files, off-Git corporate Governance, customer records, third-party proof ZIP, model providers, business rights, live deployments or existing CI modified.

## 1Z. Batch 26 — 25 full-body reads: B16 sports, B17 local shops, B18 audio, B19 memories, B21 fictional strategy, B29 apartment and B38 exercise (2026-10-13)

Frozen 835-original document cursor: **750 partly/fully text-viewed** (125 initial `TEXT_SAMPLED` plus B02–B26 each 25), **66 INDEXED_ONLY** text bodies unread, **19 BINARY_PENDING** original PDF/DOCX unread. Initial 125 samples are not exhaustively reclassified.

- [Batch26 exact-source SHA-pinned public-safe technology, product, owner and rights triage](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH26_20261013.md).
- B16 past draft Owner design hold, B17 real-merchant editorial rights, B18/B19 missing binary screenshot bytes, and B21 synthetic founder/finance and approval imagery are different evidence classes; B21 is not current PADIEM company strategy.
- B29 separate apartment product image-source notes refer to real identity and confidential legal/audit material **not** included in demo; do not reproduce it in public source audit. B38 synthetic motion exercise plan lacks clinical/real safety or independently approved customer effect.
- No original path/blob/hash/size, private Governance/drive content, protected UI product PR, user files, business permission or live deployment changed.

## 1AA. Batch 27 — 25 source reads: B39–B43 emergency, development control, B47 feedback and B49 public data (2026-10-13)

Frozen **835 originals**: **775 text-viewed at least partly** (125 initial TEXT_SAMPLED + 25 each B02–B27), **41 INDEXED_ONLY** text originals unread and **19 BINARY_PENDING** PDF/DOCX originals unread. Original 125 samples still need exhaustive classification.

- [Batch27 exact-source Git-SHA-pinned public-safe classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH27_20261013.md).
- B39/40/41 are synthetic human-reviewed emergency communication/urgency UI, not live 112, certified translation, autonomous dispatch or actual human approval.
- B42 software change-control authority versus B43 one-work-item software delivery are distinct technical products; labels like MERGEABLE or HUMAN-VERIFIED cannot substitute exact-head independent proof, real merge or deployment.
- B47 excludes feedback monitoring and automatic user scoring; B49 public-data schema/lineage does not establish actual connected API, government endorsement, dataset licences or current values.
- No original files/paths/SHAs, off-Git corporate Governance, emergency/personal records, external provider, product permissions, production service or Git history modified.

## 1AB. Batch 28 — 25 full text reads: B66, public Lab, old Core/Claw, B06 and B35 QA (2026-10-13)

Frozen **835 original** cursor: **800 original texts viewed partly or fully** (125 initial `TEXT_SAMPLED` + 25 each B02–B28), **16 INDEXED_ONLY** original text bodies unread, **19 BINARY_PENDING** PDF/DOCX bodies unread. Earlier 125 partial samples are not independently exhaustively cleared.

- [Batch28 exact-source SHA and business/technical/Owner classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH28_20261013.md).
- Specific public-approved B66 standard template must not be confused with private uploaded customer quotes, fonts/licensed assets or live product provisioning. Historic B66 demos, dev-model heuristics and HWPX source-only scan do not create present-day live authority.
- Public Padiem Lab must remain isolated from private Portfolio Console. B06 news benchmark is a dated research/economics hypothesis. B35 independent QA reports are overall FAIL due to revision lineage and/or missing files, despite narrower successful checks.
- B52 scheduling, B53 SDK, B58 writing-voice and B62 early chat visual motion/QA are demonstrations, not live deployment/consent/Owner approval.
- No original docs, confidential local Governance/private vault, customer contents, account/provider, Production status, business contracts or protected PR changed.

## 1AC. Batch 29 — final 16 unread original text bodies: source/package/test metadata and bounded QA (2026-10-13)

Immutable **835-source** cursor: **816 text originals seen at least partly** (125 initially `TEXT_SAMPLED` + 691 fully fetched in B02–B29); **0 INDEXED_ONLY** original texts unread; **19 BINARY_PENDING** original PDF/DOCX unread. Initial 125 partly sampled texts are **not** independently exhaustively reviewed.

- [Batch29 last 16 original path/blob-SHA pinned public-safe classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH29_20261013.md).
- All 16 are `TECH_PUBLIC`: pinned requirements and B54 package metadata, B02/B04 robots previews, B06/B10 historical source-only browser/test commands, B38/B58 local test commands, bounded Web–Control–Desktop non-model E2E, B35 independent QA tooling and B66 generic certified-template development tools.
- Robots Disallow is not authentication; historical source self-check is not live Owner permission; B35 overall acceptance remains exact-revision gated and B66 private real-document certification is not repeated by public synthetic tests.
- No original body/path/hash/size or local corporate Governance, customer data, executable code, model/Provider, product permission, commercial policy or live deployment changed.

## 1AD. Batch 30 — 19 original PDF/DOCX blob content reviews (2026-10-13)

**835/835 frozen originals have been inspected at least in part:** 691 full-text B02–B29 + 125 early partial samples + **19 BINARY_BODY_INSPECTED_B30**, **0 INDEXED_ONLY**, **0 BINARY_PENDING**. Initial 125 sampled text sources still require full review; no final legal/publication clearance implied.

- [Batch30 PDF/DOCX SHA-pinned source/content triage — publication-safe](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH30_20261013.md).
- **HIGH PRIORITY Owner/privacy review:** the owner-approved-public reference B66 PDF has two source paths with identical Git bytes and appears to include identifiable businesses/individuals, account identifiers and finance/quotation data. Public audit has deliberately excluded actual identifying values. Confirm rights/sanitization with Owner separately from technical readiness.
- B35: blank three-page/DOCX intake format vs commercial 10-page master DRAFT and one-page offer; unapproved price/contract hypotheses are Owner business materials. B66 Core 11 synthetic fixtures are noncustomer; standalone Sol resource PDF is text-free and renders blank; generic quotation reference is fictional.
- Git blob bytes and sizes checked on authorized desktop; in-memory PDF/OOXML read, representative page render checked, all temporary PNGs removed. No external cloud OCR, local corporate Governance, customer files, production or original source changed.

**Next:** fully reread and classify the original 125 `TEXT_SAMPLED` sources; then owner-only company Governance decision, and separate high-priority B66 source disclosure remediation if required.

## 1AE. Batch 31 — first 25 exact-source full re-reviews of the initial 125 partial text samples (2026-10-13)

**Frozen 835-original latest cursor:** 691 B02–B29 originally complete text fetches + **25 fully re-reviewed early samples** (`TEXT_FULL_REVIEWED_B31`) + **100** still `TEXT_SAMPLED` + 19 B30 PDF/DOCX body inspections = **835**. No index-only or binary pending remains. These counts are read-state bookkeeping, **not** legal or corporate publication clearance.

- [Batch31 SHA-pinned 25-file full original text review and public-safe provisional classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH31_20261013.md).
- Provisional class totals: **BUSINESS_REVIEW 11**, **MIXED_REVIEW 10**, **TECH_PUBLIC 2**, **PRODUCT_PUBLIC 1**, **TECH_OWNER_RECORD 1**.
- B35 proposal, customer-outreach templates, commercial qualification, legal/data contract drafts and source-verified market arguments require Owner-controlled evaluation and legal review before customer send or any private/public migration. No real customer responses or executed contracts were found in these source files; no draft rates or clause text copied into this report.
- Historical B14 provider direction/model route changes, Claw Ops incubation and July Personal Edition first-revenue experiment are not current live permissions, executable model lists or automatic company business policy.
- No source files, source blob SHA, original byte sizes, PDF/DOCX, local Governance, CI/code, customer information, product rights, Cloudflare Production or Git history mutated.

**Next:** 100 original `TEXT_SAMPLED` require full-source re-review (four further 25-file batches). The B66 already-public reference quotation identified in Batch30 needs separate Owner/security/privacy evaluation; audit status does not itself authorize redistribution or removal.

## 1AF. Batch 32 — 25 further complete re-reviews of early text samples (2026-10-13)

**Immutable 835-original current cursor:** 691 fully fetched B02–B29 + 25 full early-text re-reviews B31 + **25 B32 full early-text re-reviews** + **75** remaining `TEXT_SAMPLED` + 19 B30 binary bodies inspected = **835/835 viewed at least in part**. **0 INDEXED_ONLY / 0 BINARY_PENDING.** Current deep/whole-body completion bookkeeping is **741 text + 19 binary**; 75 first-pass samples await full-source re-review. Review status is not customer-data publication approval.

- [Batch32 exact original path/blob-SHA 25-file complete text review and public-safe provisional classifications](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH32_20261013.md).
- Provisional classes: `MIXED_REVIEW=9`, `BUSINESS_REVIEW=1`, `TECH_PUBLIC=8`, `TECH_OWNER_RECORD=7`.
- September search-provider W3/W4 vendor-terms assessment and prewritten outreach are **historical contractual evaluation**, not sent correspondence, current privacy agreement, paid offer, model/provider choice or Production activation. B35 internal commercial closeout artifacts and externally submitted customer-specific agreements require separate Owner/legal clearance.
- Repository agent/AI workflow, document authority, source/portal isolation, model technical approval and deployment policies remain **public technical/CTO records**; off-Git company Governance content was not read or copied. Dated provider/catalog, B62 rollout, B66 inquiry/notification and issue snapshots cannot establish a current active customer flow by themselves.
- Fixed original paths/hashes/byte sizes, customer data, real provider credentials, original source/binary files, local company Governance, code, Cloudflare Production and Git history left unchanged.

**Next:** complete 75 remaining `TEXT_SAMPLED` in three 25-file rounds (B33–B35); then draft Owner-private candidate decisions, keeping B66 public reference PDF disclosure assessment separately prioritized.

## 1AG. Batch 33 — whole-body re-review of 25 more original early text samples (2026-10-13)

**835 frozen originals:** 691 previously fully fetched B02–B29 + 25 full rereviews B31 + 25 B32 + **25 B33** + **50 pending original `TEXT_SAMPLED`** + 19 B30 PDF/DOCX inspected = **835**. All 835 have been viewed at least in part; **766 text and 19 binary** have a complete body-inspection record. Zero INDEXED_ONLY / BINARY_PENDING. Read-state completion does not authorize external publication or migration.

- [Batch33 exact 25 frozen Git blob SHA/full original text audit and provisional classification](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH33_20261013.md)
- Tally: `TECH_PUBLIC=3`, `TECH_OWNER_RECORD=3`, `PRODUCT_PUBLIC=6`, `MIXED_REVIEW=8`, `BUSINESS_REVIEW=5`.
- First-generation project vision/revenue roadmap, B60 proposed offer/discovery product and candidate business backlog are hypothesis/history—not approved present company business policy.
- Portfolio Business Registry and external-project successor tracking are development/product ownership with some business directions; preserve existing numbering, no duplicate internal folders. Public architecture/visual docs remain technical/product evidence, not `OWNER_UI_APPROVED` or runtime acceptance.
- B66 dated customer CGI onboarding and rollout records require cautious disclosure/Owner review independent of PDF, D1, test or Production status. No sensitive customer values reproduced. Local company Governance remains out of scope: not opened, mutated or republished.
- All frozen original paths, blob SHA and byte sizes unchanged; only this checkpoint, Batch33 public-safe report and manifest read-state cells changed.

**Next:** 50 initial `TEXT_SAMPLED` originals in two further 25-file batches B34–B35; then aggregate the Owner-only confidentiality/business-review decision list.

## 1AH. Batch 34 — full-body re-review of 25 original reference product documents (2026-10-14 KST)

**Immutable 835-source progress:** 691 fully fetched original text B02–B29 + 25 each B31/B32/B33/B34 = **791 fully inspected original text files** + 19 PDF/DOCX B30 inspected + **25 remaining `TEXT_SAMPLED`** = 835 original files, with no `INDEXED_ONLY` or `BINARY_PENDING`. Initial partial examination of all files is complete; full-body re-review remains on the final 25.

- [Batch34 original source SHA/25-item full-body classification and safe cross-document findings](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH34_20261013.md).
- Batch34 provisional classes: `PRODUCT_PUBLIC=21`, `MIXED_REVIEW=3`, `BUSINESS_REVIEW=1`. Most are explicitly synthetic UI reference descriptions, not Production, live AI, actual customer materials or current product approval.
- B05 original neighbor-market idea/ranking and business-monetization hypotheses are not instructions to recreate the superseded internal product workspace; current DanjiOn external successor source authority remains separate.
- B29 real-world community reference includes an identifiable operating-person reference and a historical permission statement. Verify any public-name/disclosure consent with Owner/privacy review; no personal identity or location data is reproduced in the audit.
- B35 V3 prospective institutional pilot/workshop commercial product contract is distinct from its static demo and from any approved customer-specific SOW/price. B21 founder strategy letter refers to a **fictional synthetic product demo**, not the company's private business policy.
- Original path/blob SHA/byte sizes and all original source, customer records, local company Governance, source code, Production/deploy, model and credentials remain unchanged. The sole changed files are this checkpoint, the Batch34 report and 25 read-state manifest cells.

**Next:** B35 final 25 `TEXT_SAMPLED` complete-text reviews, then sanitized aggregate register + Owner-private review/disclosure queue, with no unapproved publication changes.

## 1AI. Batch 35 — LAST 25 original samples fully inspected; frozen 835-source full-body reading complete (2026-10-14 KST)

**FROZEN SOURCE TREE:** `5476d1038993d647bf8ba241ce6a4307cccf291f`. All **835 original recognized GitHub documents** now carry whole-body inspection state:
- 691 `TEXT_FULL_FETCHED_B02`–`TEXT_FULL_FETCHED_B29`
- 125 `TEXT_FULL_REVIEWED_B31`–`TEXT_FULL_REVIEWED_B35` (25 each)
- 19 `BINARY_BODY_INSPECTED_B30` (17 PDF, 2 DOCX)
- **Zero** `TEXT_SAMPLED`, `INDEXED_ONLY`, `BINARY_PENDING`

[Batch35 public-safe 25-item original Git blob SHA review, final reading certificate and forward privacy/business disposition](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH35_20261014.md).

**Batch35 classifications:** `PRODUCT_PUBLIC=21`, `TECH_OWNER_RECORD=2`, `MIXED_REVIEW=1`, `BUSINESS_REVIEW=1`. Synthetic public safety/emergency, local model, personal archive, SDK and workflow UI reference source only. B60 dated commercial editorial selection/offer prioritization remains an Owner company-business review candidate; model offers, prices and copyrights are not freshly validated. B66 current technical source and B67 static legal research UX must not be treated as current Production/customer verification.

**Not an Owner/publication approval:** All original 835 paths, byte sizes, blob SHA and original source content remain fixed, and no original PDF, customer record, active product, cloud runtime, local company Governance or business strategy was moved/edited. B30 flagged identical CGI original/source PDF blobs containing apparent contact/financial/individual information, B29 named community/representative publicity and B35 customer proposals remain **separate Owner/privacy/legal review priorities**.

**Next governance phase (separate):** reconcile the full 835-original cross-batch provisional classes into a single source-anchored classification register, distinguish business policy vs public technical work, and prepare a separate **private Owner-only** disclosure/migration decision shortlist. No unapproved publication, original rewriting, file deletions or local Governance copying. Audit coverage is pinned historical tree only; current/future `main` changes require an independent delta audit.

## 1AJ. Batch 36 — 835-original cross-batch classification register and Owner-disposition queues (2026-10-14 KST)

**The original whole-body reading was completed in B35.** B36 has now reconciled **all 835 original file paths 1:1** from B02–B35 per-source batch tables, with **no original path/blob SHA/byte count/read-state drift, duplicate, missing or unmatched row**. B06's 5 extra reinspection notes were already part of the early sampled inventory; these do not inflate the original count.

- [**Complete 835-source per-path/source-SHA/class/follow-up register**](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_CLASSIFICATION_REGISTER_20261014.tsv)
- [**Batch36 consolidated governance findings, exact totals and sanitized Owner decision index**](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_CONSOLIDATED_20261014.md)
- Provisional class totals: `TECH_PUBLIC=376`, `PRODUCT_PUBLIC=166`, `TECH_OWNER_RECORD=137`, `MIXED_REVIEW=126`, `BUSINESS_REVIEW=30`. Total 835.
- Follow-up queues (single assignment per original): `PRIVACY_CRITICAL_OWNER=2`, `IDENTITY_CONSENT_OWNER=6`, `CUSTOMER_COMMERCIAL_OWNER=20`, `PROVIDER_OFFER_OWNER=4`, `COPYRIGHT_CHECK=3`, `BUSINESS_OWNER=17`, `MIXED_OWNER_REVIEW=111`, `TECH_PRODUCT_CONTRACT_ONLY=672`. Total 835.
- **Owner/security/legal priority:** B66 original CGI PDFs in a publicly distributed reference tree have potentially real-looking individual/contact/financial details; public values are not copied, and disclosure/remediation or history rewrite was **not** undertaken. Real-person/community reference consent and B35 customer-commercial proposal rights also remain Owner decisions.
- Business/mixed baseline 156 is a classification population; specialized follow-up 163 is a separately prioritized queue, **not an additive count**.
- No private local Governance policy was read/moved/reproduced. No original source, company policy, user/private/customer data, code, provider/model rights, secrets, deployment or original Git history changed. The frozen-original register covers only `5476d1038993d647bf8ba241ce6a4307cccf291f`; changed/new `main` sources need later delta audit.

**Next:** Owner-only business/identifiable-content disposition and *separately scoped* post-freeze GitHub document delta review, without assuming publishing rights or moving entire files wholesale.

## 1AK. Batch 37 — historical-freeze-to-current document delta audit (2026-10-14 KST)

**Old frozen 835-source baseline:** `5476d1038993d647bf8ba241ce6a4307cccf291f`. **New bounded `main` snapshot:** `4bf9056459c2f500f6a069a4a8301ad21386cd12`. Exact Git compare: **86 changed paths**, **48 document artifacts** (`.md/.txt/.pdf/.docx/.tsv`), **38 other code/config**. Among 48 document artifacts, **38 are B02–B36 self-generated audit metadata**; **8 newly added** technical documents and **2 modified** existing source policies are substantive. 0 new PDFs/DOCX, deleted documents or renamed documents.

- [Batch37 whole-body review and risk boundaries for 10 substantive changed documents](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH37_DELTA_20261014.md).
- [Exact 48-row delta source/status/blob-SHA/size and classification register](GITHUB_DOCUMENT_GOVERNANCE_AUDIT_POSTFREEZE_DELTA_REGISTER_20261014.tsv).
- Classification by document artifact: `AUDIT_META=38`, `TECH_OWNER_RECORD=8`, `TECH_PUBLIC=1`, `MIXED_REVIEW=1`, `BUSINESS_REVIEW=0`.
- The two modified pre-existing sources are the production deployment/rollback policy and P01 live SSE release authority. Their original Git blob SHAs match the original 835-source record; amendments concern single-Owner process and technical runtime verification, **not automatic Production authorization or removal of actual GitHub protections**.
- The new technical resource/streaming documents do not authorize new model tiers, customer access, provider contracts or unlimited Worker memory. Actual deployed B14/B62/Engine/Claw/B66 state remains a separate exact-main/served verification.
- Previous P0 disclosure matter — B66 public reference CGI PDF pair with apparent sensitive individual/contact/financial content — **unchanged and unresolved**; publication/removal/history response reserved to Owner/security/legal. Do not repeat those identifying values in GitHub audit reports.
- **The original 835 fully inspected source count stays 835.** This new register does not silently append self-generated audit documents into the frozen inventory; future `main` commits after the snapshot require a new delta.

**No original document content, binaries, local private Governance, product code, provider configuration, business strategy, customer data, or Production was changed by Batch37.**

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
