# Cloudflare Pages Git Connection Runbook

- Status: portfolio operating policy
- Owner: Web CTO
- Applies to: static UI/UX review artifacts and product-specific Cloudflare Pages projects
- Related phase policy: `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- Related playbook: `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`

## 1. Decision

A Cloudflare Pages project connected to a GitHub repository, branch, and root directory is a **hosting connection**. It is not automatically any of the following:

- a merge to `main`;
- a product release;
- production approval;
- `UI_APPROVED` or `UX_APPROVED`;
- backend authorization;
- evidence that the configured project serves the intended Business;
- evidence that the current URL serves the reviewed exact commit.

For a static Phase 1 UI reference, a dedicated Pages project may be created before UI approval so that the user and Web CTO can inspect the interface in a real browser. This is called **hosted review**, not product production deployment.

## 2. Terms that must not be conflated

### 2.1 Code change

Files are added or changed on a Git branch. No hosted URL is implied.

### 2.2 Pull request

A GitHub review object compares a head branch with a base branch. A PR does not create a correct Pages project by itself.

### 2.3 Pages project and Git connection

An account-side Cloudflare object defines:

- Pages project name;
- GitHub repository;
- primary branch, labelled `Production branch` by Cloudflare;
- root directory;
- build command;
- build output directory;
- environment variables and access policy.

Cloudflare's field name `Production branch` means the primary branch for that Pages project. It does **not** mean that AI Revenue Lab has approved a product production release.

### 2.4 Branch preview

A deployment produced for a non-primary branch of a correctly configured Pages project. It is useful only when the project identity, repository, root directory, branch, and exact commit are verified.

### 2.5 Hosted review URL

A browser-accessible URL used to inspect a UI or UX artifact. It may be the Pages project's primary URL or a branch URL. It remains review evidence only.

### 2.6 Product production release

A separately authorized runtime release after the applicable UI, UX, backend, security, and operational gates. A hosted static reference is not this release.

## 3. Mandatory project isolation

Each independently reviewed Business or product surface must use the correct dedicated Pages project unless a documented portal decision explicitly defines a shared host.

Do not:

- reuse an unrelated Business's Pages project;
- accept a successful deployment bot comment from the wrong project;
- infer correctness from a green Cloudflare status alone;
- merge to `main` merely to obtain a viewable URL;
- call a hosted UI reference a production release;
- advance to UX or backend because a URL exists.

A deployment under `ai-revenue-personal-video-archive` cannot prove World Feed. A deployment under any wrong project name is invalid evidence even if the deployed commit is correct.

## 4. Static UI review connection procedure

### 4.1 Preconditions

Before creating the Pages project, record:

- repository;
- exact head branch;
- exact head SHA;
- static root directory;
- expected entry file;
- expected local asset paths;
- intended Pages project name;
- whether the URL is public or protected;
- current phase and approval state.

The branch may remain Draft and unmerged.

### 4.2 Cloudflare Pages configuration

In Cloudflare:

```text
Workers & Pages
→ Create
→ Pages
→ Connect to Git
```

Configure the exact values approved for the Business.

For a plain static reference whose `index.html` is already in the selected root:

```text
Build command: <empty>
Build output directory: .
```

Do not add a build system merely to make Pages accept the project.

### 4.3 Required post-connection verification

After the first deployment, verify all of the following:

1. Pages project name is correct.
2. Connected GitHub repository is correct.
3. Configured primary branch is correct.
4. Root directory is correct.
5. Deployed commit equals the expected exact SHA.
6. The URL host belongs to the correct Pages project.
7. The page title and visible product identity match the intended Business.
8. CSS, JavaScript, images, fonts, and other local assets load without failure.
9. Desktop and mobile layouts can be reviewed.
10. Review controls and signature motion work where required.
11. The PR and phase status remain unchanged unless separately approved.

A bot comment or dashboard status without these checks is not sufficient evidence.

## 5. Evidence classification

Record hosted evidence with one of these labels:

- `HOST_CONNECTION_PENDING`
- `HOST_CONNECTION_VERIFIED`
- `HOST_CONNECTION_WRONG_PROJECT`
- `HOST_CONNECTION_WRONG_ROOT`
- `HOST_CONNECTION_WRONG_SHA`
- `HOSTED_REVIEW_READY`
- `HOSTED_REVIEW_FAILED`
- `PRODUCT_PRODUCTION_RELEASED`

`HOSTED_REVIEW_READY` is compatible with `UI_NOT_READY`, `UI_CONDITIONALLY_READY`, or `UX_NOT_READY`. Hosting does not grant an approval status.

## 6. Responsibility and proof boundaries

### Web CTO

- defines the intended repository, branch, root, project name, and evidence standard;
- verifies GitHub exact head and changed scope;
- verifies the resulting hosted identity and phase classification;
- does not claim Cloudflare account changes without direct evidence.

### Cloudflare account operator

- creates or changes the Pages project in the Cloudflare control plane;
- connects GitHub;
- enters branch, root, build, output, environment, and access settings;
- reports the resulting project and URL.

### Web or Local worker

- may prepare static files and focused verification evidence;
- must not reuse another project's host for convenience;
- must not classify hosted review as production;
- must not claim account-side work it could not perform.

A GitHub connector can verify repository state. It cannot by itself prove that a new Cloudflare Pages project was created or configured.

## 7. World Feed Phase 1 example

For the recovered World Feed reference in PR #158, the intended hosted-review connection is:

```text
Pages project name: ai-revenue-world-feed
Repository: skerishKang/ai-revenue-lab
Primary branch in Cloudflare: feat/business-06-world-feed-ui-155
Root directory: reference/business-06-world-feed-v1
Build command: <empty>
Build output directory: .
Environment variables: none
Expected project URL: https://ai-revenue-world-feed.pages.dev
Reviewed recovery head: 99981006dcf792c359795a0c618c92a800d65c0d
```

The Cloudflare primary-branch field may display `Production branch`. In portfolio governance this remains a Phase 1 hosted review until the user explicitly approves the UI and later release gates are satisfied.

The previously generated URL under `ai-revenue-personal-video-archive` is `HOST_CONNECTION_WRONG_PROJECT` and must not be used as World Feed evidence.

## 8. Failure handling

When a wrong project, root, branch, or SHA is discovered:

1. stop presenting the URL as valid evidence;
2. record the mismatch in the PR or issue;
3. do not compensate by merging unrelated code;
4. correct the Pages project connection or create the correct dedicated project;
5. redeploy from the intended branch and root;
6. repeat the post-connection verification;
7. preserve the phase gate and approval state.

## 9. Reporting template

```text
Hosted review classification: HOSTED_REVIEW_READY / ...
Pages project: ...
URL: ...
Repository: ...
Configured primary branch: ...
Root directory: ...
Expected exact SHA: ...
Observed deployed SHA: ...
Project identity check: PASS / FAIL
Asset loading check: PASS / FAIL
Desktop review: PASS / FAIL
Mobile review: PASS / FAIL
PR state: ...
UI state: ...
UX state: ...
Backend state: ...
Production release claim: NO / YES with separate authorization evidence
```

## 10. Governing rule

When the words preview, deploy, production, Pages, hosted, branch, or release appear in another document, interpret and rewrite them according to this runbook. Ambiguous wording must be corrected before it is used to authorize work.