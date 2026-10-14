# GitHub Governance document audit — Batch 38: post-B37 changes and B66 private custody consistency (2026-10-14 KST)

> **Scope:** compare fixed B37 audit snapshot `4bf9056459c2f500f6a069a4a8301ad21386cd12` against bounded `main` snapshot `05463d3c2fce6c0dc66b00f4fc921cf86b946546` (7 intervening commits). This is a delta document review, **not** a rescan/recount of the separately frozen 835 original sources. B38 repairs two narrowly scoped publicly reviewable technical files only; private business policy stays outside public Git.

## Actual bounded delta

The direct commit comparison returned **39 changed paths**, of which **10 were document artifacts** (`.md/.txt/.pdf/.docx/.tsv`): **5 modified Markdown**, **2 added Markdown** and **3 removed PDF**. Of those 10 documents, **3 are B37's own audit ledger/report/checkpoint**; **7 are substantive changes** (4 Markdown, 3 removed PDF). Remaining 29 paths are code/config/assets requiring their own runtime/source evidence, not implied by this document audit.

| Path or scope | Delta | B38 disposition |
| --- | --- | --- |
| `AGENTS.md` | modified | Correctly references separate **local-only** `사업방침/` and `운영방침/` policy folders; only public reference/location text, not their private business substance. Do not recreate a public company-policy folder. |
| `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` | modified | Same local private-governance referral and single CTO operating source; substantive private business choices remain Owner-controlled, current technical safety/CI unaffected. |
| `docs/products/b66/TEMPLATE_CUSTODY_POLICY.md` | modified | Source had **contradictory dated statements**: obsolete 2026-10-09 CGI publication examples/tables remained next to 2026-10-14 Owner's CGI private-publication withdrawal. This B38 branch corrects the operative narrative/table, preserves prior history as history only, and fixes escaped line-break tokens in the technical status block. |
| `reference/b66-public-standard-templates/cgi/v1/README.md` | modified | Public pointer now states owner withdrew CGI source/derived artifacts from publicly reachable current Git HEAD. Readme/test only; private R2/D1 access and previously approved history remain separate. |
| `reference/b66-public-standard-templates/cgi/v1/glm53/template/base_document.pdf` | removed | Customer-specific source comparison PDF removed from current Git tree by security PR #4619; does not erase past commits. |
| `reference/b66-public-standard-templates/cgi/v1/sol61/template/resources.pdf` | removed | Customer-specific compiled PDF resource removed from current Git tree by security PR #4619; does not erase past commits. |
| `reference/b66-public-standard-templates/cgi/v1/source/original.pdf` | removed | Customer source PDF removed from current Git tree by security PR #4619; private original/R2 bundle separately verified, history review outstanding. |
| `docs/operations/GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH37_DELTA_20261014.md` | added | Prior self-generated audit report; no new business policy |
| `docs/operations/GITHUB_DOCUMENT_GOVERNANCE_AUDIT_POSTFREEZE_DELTA_REGISTER_20261014.tsv` | added | Prior self-generated exact-source delta ledger; not an original |
| `docs/operations/GITHUB_DOCUMENT_GOVERNANCE_AUDIT_CHECKPOINT_20261013.md` | modified | B37 audit bookmark only; unchanged original source count |

## Focused additional confidentiality check

B66 privacy PR #4619 merged at `fb202b34728023303164cc8f947035d9b507b143`, verified that **19 CGI-specific files** were removed from current public Git HEAD and only a general README plus anti-republication regression remain in that release directory. Its mandatory branch tests, including B66 UI parity, passed for the exact reviewed HEAD.

During B38 follow-up, the public `reference/business-66-padiem-quote-v1/tests/cgi-v2.test.cjs` was discovered to contain real-looking CGI representative/business/contact identifiers in a *synthetic test fixture*. B38 replaces those values with **invented fixture identifiers** while retaining the same QuoteCore totals, approved layout, field mapping, rendering contract and negative guards. The report intentionally omits real name, account identifiers, addresses, contact details and numeric customer identifiers.

## Customer ownership and outstanding security work

- Existing B66 D1 contains **one approved CGI Saved Quote Skill** assigned to a single registered user/workspace. A subsequent read-only D1 lookup using the **actual customer login identity** confirmed that same user's ownership, with zero alternate account ownership. This **does not** represent a transfer of permission or a new account; no customer login email is printed in this public document.
- The CGI certified preview/base and certified PDF bundle were independently verified to exist in the **private** Cloudflare R2, and original PDF checksums matched existing two-volume private Vault backups.
- **Unresolved:** prove exact served deployed B66 revision, CGI account positive preview/PDF and a different account's 403/404 (including object and source download), customer library R2 upload/original read-back/version/retention E2E (#4316), and decide appropriate prior Git history/fork/CDN/cache exposure handling. Removing current Git HEAD files is **not** historical erasure.
- The public CGI renderer/JavaScript may remain as **generic code**, but no real customer identity/source fields belong in public fixtures or built assets. Any additional secret/PII candidate found outside this bounded scope requires security triage without pasting values into an issue.
- No branch policy, D1/R2 object owner, customer file bytes, login credential, provider/model permission, live Production configuration, business agreement or price term is changed by B38.

## Review outcome and scope guard

**B38 document-delta review: COMPLETE for the 10 bounded document artifacts.** Original historic 835 inventory and B36 per-source classes retain their frozen original scope. This repair does **not** certify 29 changed non-document paths, Production, customer-library readiness, history sanitization or acceptance of separate unpublished corporate business plans. Next maintenance should use the latest accepted main snapshot as a new incremental baseline only when fresh document changes warrant it; avoid endless self-generated audit document loops.

**Files intentionally changed by B38:** (1) existing public technical custody policy, (2) existing B66 synthetic browser contract fixture, (3) this concise report and (4) previous audit checkpoint. No new technical/private policy, duplicated platform, B66 R2 storage or business-rule changes.
