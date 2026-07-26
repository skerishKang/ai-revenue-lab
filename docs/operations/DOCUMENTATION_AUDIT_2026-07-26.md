# Documentation Audit — GitHub and Cloudflare hosting terminology

- Date: 2026-07-26
- Auditor: Web CTO
- Base commit: `d443061a6ac68be26dae79a03c0423d884e5dbae`
- Audit trigger: World Feed Phase 1 hosted-review guidance failure
- Corrective branch: `docs/fix-pages-git-connection-operations`

## 1. Audit objective

Review the repository documents most likely to govern or describe:

- GitHub branches, exact heads, and pull requests;
- Cloudflare Pages or Workers Git connections;
- preview and hosted-review URLs;
- staging and production terminology;
- UI, UX, backend, and release gates;
- cross-project deployment evidence.

Correct any wording or procedure that could cause these concepts to be conflated.

## 2. Audit method and limits

The audit used:

- direct reads of the current `main` documents;
- recent commit history for `Cloudflare`, `preview`, UI-phase policy, and deployment changes;
- changed-file inventories from relevant pull requests;
- direct reads of identified product-specific deployment and staging documents;
- the World Feed PR #158 and Cloudflare bot evidence that exposed the wrong-project connection.

The repository's code-search index returned no results during this audit. Therefore, the audit did not claim an infallible full-text scan of every byte in the private repository. It instead inspected the canonical portfolio policies, index documents, candidate backlog, root README, and all deployment documents discoverable from relevant commit and PR history. Future documents containing `Pages`, `Workers`, `preview`, `deploy`, `production branch`, `hosted`, or `release` remain governed by the new runbook.

No Cloudflare account settings, application code, runtime configuration, or product data were changed by this documentation audit.

## 3. Documents reviewed and findings

| Document or evidence | Finding | Action |
|---|---|---|
| `README.md` | Portfolio architecture and deployment lifecycle are high-level; no Pages connection procedure or wrong-project instruction. | No change required. |
| `docs/operations/README.md` | Missing hosted-review terminology and no authoritative Pages Git-connection link. | Corrected and expanded. |
| `docs/operations/UI_UX_BACKEND_PHASE_GATES.md` | `production deployment` was prohibited in Phase 1, but isolated static hosted review was not explicitly distinguished. This ambiguity encouraged overcomplication. | Rewritten to separate Git state, hosting state, and phase state; hosted review is explicitly allowed without advancing gates. |
| `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` | Screenshots and branch previews were evidence, but the default user inspection method and correct dedicated Pages connection were not defined. | Rewritten to make dedicated hosted browser review the default when useful and to add connection/evidence rules. |
| `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md` | Correctly states UI-only sequence and does not claim that a deployed project or reference assigns approval. | No change required. |
| `apps/personal-video-archive/README.md` | Already names the dedicated Pages project and explicitly rejects another Business's bot-attached project as a deploy target. It also says the table is intended configuration only. | No substantive change required; treated as a compliant example. |
| `apps/korean-ai-platform/docs/CLOUDFLARE_WORKER_DEPLOYMENT.md` | Mixed a historical feature-branch Workers Build setting with production terminology and did not clearly distinguish intended post-merge state from currently verified account state. | Corrected with historical/current-proof boundaries, dedicated Worker identity checks, and release terminology. |
| `apps/living-travel/docs/staging-evidence/issue-74/REPORT.md` | Called the Pages primary project URL `Production origin` inside an external staging report. This was materially ambiguous. | Corrected to `Pages primary project origin used for staging`; added explicit non-production classification and freshness limits. |
| Personal Edition static preview implementation from PR #56 | Preview builder and fixtures were code, not a general hosting policy. No separate ambiguous operating document was found in the changed-file inventory. | No documentation change required. |
| Living Learning static preview implementation from PR #82 | Changed-file inventory contained static preview files and tests, not a general hosting runbook. | No documentation change required. |
| World Feed PR #158 Cloudflare bot comment | Deployment succeeded under `ai-revenue-personal-video-archive`, an unrelated Pages project. | Classified as wrong-project evidence; documented as the incident example. |
| Portfolio Console PRs #159 and #160 hosted status notes | Correctly excluded previews created under the wrong Personal Video Archive project. | No correction required; their exclusion logic matches the new runbook. |

## 4. Systemic problems identified

### 4.1 One word represented several operations

The words `deploy`, `preview`, and `production` were used for:

- static review hosting;
- a Pages branch deployment;
- a Pages primary project URL;
- a Worker runtime deployment;
- staging infrastructure;
- final product production release.

This was unsafe because each operation has different authorization and evidence requirements.

### 4.2 Cloudflare project identity was not a universal acceptance check

A successful Cloudflare bot status could be attached from an unrelated project. Existing product-specific documents sometimes handled this correctly, but the portfolio policy did not make the check mandatory for every Business.

### 4.3 GitHub proof and Cloudflare proof were mixed

GitHub can prove files, branches, SHAs, changed scope, and PR state. It does not prove account-side Pages project settings. Conversely, a Cloudflare success status does not prove that the GitHub scope or portfolio phase is approved.

### 4.4 Cloudflare `Production branch` was easy to misread

Cloudflare uses this term for a project's primary deployment branch. Portfolio governance uses production to mean a separately authorized product release. The same phrase therefore required an explicit translation rule.

### 4.5 User inspection was treated as evidence-file inspection

For a site-like UI, directing the user to large PNGs in GitHub is inferior to a correctly connected browser site. Screenshots remain important evidence, but they are not the preferred user review surface when static hosting is straightforward.

## 5. Repository-wide corrections

The corrected policy now requires:

1. a dedicated Pages or Worker project for the intended Business;
2. verification of project name, repository, branch, root, exact SHA, URL identity, and assets;
3. rejection of green deployments from unrelated projects;
4. separate tracking of Git state, hosted-review state, phase approval, and product release;
5. use of `hosted review` for a static UI/UX inspection site;
6. use of `product production release` only after separate authorization;
7. explicit acknowledgement that Cloudflare's `Production branch` label does not grant portfolio production status;
8. truthful control-plane claims only when Cloudflare account evidence exists;
9. no merge to `main` merely to obtain a review URL;
10. no automatic UX or backend transition because a URL exists.

## 6. New canonical documents

- `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`
- `docs/operations/incidents/2026-07-26-cloudflare-pages-git-connection-confusion.md`

The runbook governs future ambiguous terminology. The incident record preserves the specific failure and accountability.

## 7. World Feed corrected example

```text
Purpose: Phase 1 hosted UI review
Pages project: ai-revenue-world-feed
Repository: skerishKang/ai-revenue-lab
Branch: feat/business-06-world-feed-ui-155
Root directory: reference/business-06-world-feed-v1
Build command: empty
Build output directory: .
Expected URL: https://ai-revenue-world-feed.pages.dev
Reviewed recovery head: 99981006dcf792c359795a0c618c92a800d65c0d
Product production release: NO
UI approval: pending explicit user approval
UX/backend authorization: NO
```

The URL produced under `ai-revenue-personal-video-archive` is not World Feed evidence.

## 8. Follow-up rule

When future repository work introduces or changes any Cloudflare Pages or Workers document, the reviewer must check it against the canonical runbook before merge. Product-specific documents may add stricter rules but must not redefine hosted review as production or accept cross-project deployment evidence.
