# Incident — Cloudflare Pages Git connection confused with deployment

- Date: 2026-07-26
- Area: portfolio UI review operations
- Severity: process failure; no production data or runtime impact
- Owner: Web CTO
- Related work: Business 6 · World Feed, Issue #155, Draft PR #158
- Corrective runbook: `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`

## 1. Summary

During World Feed Phase 1 UI review, the Web CTO gave incorrect and inefficient guidance by conflating three different operations:

1. preserving UI files on a Git branch;
2. deploying or merging product code;
3. creating a dedicated Cloudflare Pages project and connecting it to the correct GitHub repository, branch, and root directory.

The user needed a normal browser address for the static UI reference. The correct next operation was simple: create the World Feed Pages project, connect the existing GitHub branch, and set the static reference directory as the root.

Instead, the Web CTO first directed the user toward GitHub PNG files, then presented a Cloudflare branch URL belonging to the unrelated `ai-revenue-personal-video-archive` project, then discussed additional deployment work and account limitations before clearly stating the required Pages project connection.

This was a reasoning and operating-process failure by the Web CTO.

## 2. What happened

The World Feed UI existed on:

```text
Repository: skerishKang/ai-revenue-lab
Branch: feat/business-06-world-feed-ui-155
Root: reference/business-06-world-feed-v1
Exact recovered head: 99981006dcf792c359795a0c618c92a800d65c0d
```

Cloudflare automatically produced a deployment comment under:

```text
ai-revenue-personal-video-archive
```

That project identity did not match World Feed. The URL was therefore invalid as World Feed evidence regardless of its green deployment status.

The correct action was:

```text
Create Pages project: ai-revenue-world-feed
Connect repository: skerishKang/ai-revenue-lab
Set primary branch: feat/business-06-world-feed-ui-155
Set root directory: reference/business-06-world-feed-v1
Build command: empty
Build output directory: .
```

No merge, redesign, backend work, or product production release was needed.

## 3. Incorrect guidance

The Web CTO made the following errors:

- treated GitHub-hosted screenshots as an adequate default user review method even after the user said they were difficult to see;
- presented a branch preview from the wrong Cloudflare project;
- described that preview as potentially useful before verifying project identity;
- implied that a separate deployment implementation might be necessary;
- failed to distinguish Cloudflare's `Production branch` field from portfolio product-production approval;
- focused on lack of direct Cloudflare tool access before first giving the simple account-side connection operation;
- did not have an authoritative runbook that separated hosted review from production release.

## 4. Why the guidance was wrong

A static UI reference already containing `index.html`, CSS, JavaScript, and local assets does not require a new application deployment design. Cloudflare Pages can serve the selected Git repository subdirectory directly.

The operational decision has two separate planes:

- GitHub plane: branch, exact SHA, files, PR, and scope;
- Cloudflare control plane: Pages project, connected repository, primary branch, root directory, build/output settings, URL, and access policy.

Success in one plane does not prove correctness in the other. The Web CTO verified GitHub but failed to classify the Cloudflare project mismatch before presenting the URL.

## 5. Impact

- the user spent additional time trying to inspect small GitHub images;
- an unrelated URL was presented and then withdrawn as unreliable;
- the distinction between hosted review and product production release became unnecessarily confusing;
- the UI review process appeared more complex than it was;
- trust in the operating process was reduced.

No source code was merged because of this error. No UX or backend phase was authorized. No production user data was affected.

## 6. Root causes

### 6.1 Terminology gap

Existing policy prohibited `production deployment` during Phase 1 but did not explicitly define a dedicated static hosted-review connection as permissible review infrastructure.

### 6.2 Project-identity check omitted

The presence of a successful Cloudflare bot comment was treated as evidence before verifying that the Pages project matched the intended Business.

### 6.3 Tool-boundary reasoning error

The absence of a Cloudflare control-plane connector was allowed to obscure the user's simple requested operation. Tool access limits should affect who clicks the account-side controls, not the correctness or clarity of the operating instruction.

### 6.4 Evidence-order error

The Web CTO prioritized screenshot recovery and PR evidence before establishing the easiest way for the user to inspect the actual site interactively.

## 7. Corrective actions

Completed in the documentation branch:

- created `CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`;
- separated code changes, PRs, Pages connections, branch previews, hosted review, and product production releases;
- declared wrong-project deployments invalid evidence;
- added exact project/repository/branch/root/SHA verification requirements;
- clarified that Cloudflare's `Production branch` label does not grant portfolio production status;
- clarified control-plane proof boundaries;
- updated phase and UI-first policies to permit isolated hosted review without advancing phase gates;
- updated the operations index.

## 8. Prevention rules

Before sharing any Pages URL, the Web CTO must verify:

1. project name;
2. repository;
3. branch;
4. root directory;
5. exact deployed SHA;
6. visible product identity;
7. asset loading;
8. phase classification.

A green deployment status under the wrong Pages project is a failure, not a partial success.

When the user asks to see a static UI as a site, the default response is to establish or use the correct dedicated Pages Git connection. Do not redirect the user to raw screenshots as the primary review mechanism unless hosted review is unavailable or explicitly unnecessary.

## 9. Accountability statement

The failure was not caused by the user, the World Feed UI files, or GitHub. It was caused by the Web CTO's incorrect operational framing and incomplete terminology. The documentation now records that error explicitly so the same pattern is not repeated.