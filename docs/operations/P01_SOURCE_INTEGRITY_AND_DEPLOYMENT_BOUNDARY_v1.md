# P01 Source Integrity and Deployment Boundary v1

Refs: #1231, #1098, #1101, #1177, #1198, #1315

## Purpose

P01 platform work must be able to run source-integrity CI without causing or being reported as a Production deployment.

This document defines the repository-side boundary between:

```text
SOURCE_INTEGRITY_CI
PREVIEW_DEPLOYMENT
PRODUCTION_DEPLOYMENT
```

## Definitions

### SOURCE_INTEGRITY_CI

Repository-owned validation for code, contracts, tests, static checks, dry-run bundles, and network-free conformance.

Allowed examples:

```text
pytest / node --test / compileall / static contract checks
pywrangler deploy --dry-run
workflow echo evidence such as PRODUCTION_DEPLOYMENT=0
```

### PREVIEW_DEPLOYMENT

A non-production branch preview created by an external integration such as Cloudflare Pages bot.

A preview comment is not itself a Production mutation. However, for P01/Core/Engine/Control-Plane-only changes it is an unnecessary side effect unless explicitly required for a product UI/release gate.

If the preview is controlled by Cloudflare project settings rather than repository workflows, GitHub source cannot certify that setting by itself. The retained evidence must say so explicitly.

### PRODUCTION_DEPLOYMENT

Any mutation that changes public production traffic, production alias, production Cloudflare Pages/Workers deployment, DNS/custom-domain binding, production secrets, or live provider/runtime activation.

Production deployment requires separate owner/CENTRAL authorization and must not be inferred from a successful source-integrity CI run.

## Repository-owned guard

The repository includes `.github/scripts/p01_deployment_boundary_guard.py` and `.github/workflows/p01-deployment-boundary-guard.yml`.

The guard fails if a non-release GitHub Actions workflow contains live deployment commands such as:

```text
cloudflare/pages-action
wrangler pages deploy
wrangler deploy
pywrangler deploy
```

Dry-run bundle checks remain allowed only when the command line contains `--dry-run`.

## Required reporting language

For P01/Core/Engine/Control-Plane PRs, reports should distinguish:

```text
SOURCE_INTEGRITY_CI = PASS | FAIL | NOT_RUN
REPOSITORY_OWNED_PREVIEW_DEPLOYMENT = 0 | EXPLICITLY_AUTHORIZED | UNKNOWN
EXTERNAL_CLOUDFLARE_PAGES_PREVIEW = YES | NO | UNKNOWN
PRODUCTION_DEPLOYMENT = 0 | AUTHORIZED_MUTATION
```

Do not collapse a repository-wide Cloudflare preview comment into `PRODUCTION_MUTATION`.
Do not claim that external Cloudflare project settings were changed unless that setting was actually read or mutated through the Cloudflare authority surface.

## P01 invariants

```text
P01_CORE_ONLY_PR -> NO_REPO_OWNED_DEPLOYMENT_COMMAND
P01_ENGINE_ONLY_PR -> NO_REPO_OWNED_DEPLOYMENT_COMMAND
P01_CONTROL_PLANE_ONLY_PR -> NO_REPO_OWNED_DEPLOYMENT_COMMAND
P01_ARCHITECTURE_DOC_ONLY_PR -> NO_REPO_OWNED_DEPLOYMENT_COMMAND
CI_SOURCE_INTEGRITY = PRESERVED
B14_SOURCE_MUTATION = 0 unless separately authorized
B62_SOURCE_MUTATION = 0 unless separately authorized
PRODUCTION_DEPLOYMENT = 0 unless separately authorized
```

## External Cloudflare Pages setting gate

If Cloudflare Pages still posts previews for P01-only PRs after this repository-side guard, the remaining action is outside the GitHub source tree:

```text
CLOUDFLARE_PROJECT_SETTING_AUDIT_REQUIRED = YES
DISABLE_OR_PATH_FILTER_EXTERNAL_PREVIEW_FOR_P01_ONLY = REQUIRED_WHERE_AVAILABLE
```

That external setting change is not performed by this document or by the repository guard.
