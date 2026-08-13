# AI Development Operating Policy

Status: Canonical  
Scope: repository-wide development, validation, review, merge, and Production verification  
Authority: Issue #148

## Purpose

AI Revenue Lab separates product authority, implementation, real-environment validation, and final technical review so that completion claims are tied to reproducible evidence rather than worker self-report.

## Required roles

1. **User / Product Owner** — product goals, priorities, material UX/business decisions, final merge or Production authorization.
2. **Web CTO** — work contract, architecture and safety boundaries, acceptance criteria, independent final review.
3. **Web Developer** — implementation on the authorized branch, tests, Draft PR, CI response, implementation report.
4. **Local Validator** — independent execution of the exact PR HEAD in the required real environment; source remains unmodified unless a separate implementation task explicitly authorizes edits.

One person or model may perform more than one role only when the responsibilities and evidence for each stage remain explicitly separated. An implementer does not self-validate as an independent Local Validator.

## Canonical workflow

```text
User request
→ Web CTO work contract
→ Web Developer implementation
→ GitHub CI
→ Local validation
→ Web CTO final review
→ User approval
→ Merge
→ Production verification
```

A stage may be marked not required only when the work contract or final CTO review records why it is inapplicable.

## Work identity

Before implementation, record:

- repository and default branch;
- exact base SHA;
- target branch;
- issue/work-order authority;
- allowed paths;
- forbidden paths;
- non-goals;
- required checks and evidence;
- acceptance criteria.

Relative statements such as “latest main” are not sufficient revision identity.

## Branch and scope rules

- Do not make ordinary development changes directly on `main`.
- Do not force-push shared or protected work without explicit authority.
- Do not include unrelated dirty files or files outside the work contract.
- Do not weaken acceptance criteria, assertions, tests, safety checks, or failure handling merely to make an implementation pass.
- Do not hide failed, skipped, warning, or untested states.
- Do not expose secrets, credentials, personal data, or private evidence in source, logs, PRs, or reports.

## Web CTO responsibilities

The Web CTO:

- re-reads current remote state before work and before final review;
- fixes objective, non-goals, scope, exact base, contracts, and acceptance criteria;
- identifies security/privacy/deployment boundaries;
- reviews the actual diff and current exact head rather than trusting implementation summaries;
- checks CI sufficiency and Local Validation revision identity;
- assigns the final technical status.

Only the Web CTO may assign:

```text
READY
CONDITIONALLY_READY
NOT_READY
```

`READY` is a technical/review status, not an automatic merge or deployment command.

## Web Developer responsibilities

The Web Developer:

- starts from the authorized exact base or records drift before proceeding;
- uses the authorized branch and paths;
- implements code, tests, and documentation required by the work order;
- creates a Draft PR;
- reports exact base/head, changed files, diff statistics, commands, exits, pass/fail/skip counts, CI, and limitations;
- returns unresolved environment-dependent validation to the Local Validator.

The Web Developer may not self-assign final CTO status.

## Local Validator responsibilities

The Local Validator:

- checks out the exact remote PR HEAD;
- records actual tested SHA and repository cleanliness/dirty state;
- runs the required build, tests, browser flows, external-service checks, or OS/hardware-specific checks;
- records commands, exit/status, relevant stdout/stderr, screenshots/artifacts, console/page/network failures, and reproduction steps;
- reports whether source was modified during validation.

If product source is modified, the result is not independent `LOCAL_PASSED`; the change returns to implementation as a separate revision.

## CI rule

GitHub CI is necessary when configured for the scope, but CI alone is never sufficient evidence of completion. UI/UX, browser behavior, external APIs, authentication, databases, hardware/OS dependencies, and Production surfaces generally require additional real-environment validation.

If hosted CI is absent or does not cover a required behavior, record that limitation and the substitute validation. Never claim nonexistent CI passed.

## Revision invalidation

Evidence belongs to the SHA it tested. A new commit invalidates prior-head evidence unless the Web CTO explicitly documents why a particular evidence item remains applicable. Required validation is repeated whenever changed behavior can affect its result.

## Merge and Production

Before merge:

- the reviewed head must match the evidence head;
- required acceptance criteria must pass or be explicitly classified as approved non-goals/conditions;
- required CI and Local Validation must be complete;
- scope and security boundaries must pass final review.

After merge, a Production-capable change is not complete until the configured Production surface is verified against the authorized merge/release revision. HTTP 200 or an accessible URL alone does not prove revision identity.

## Prohibited claims and actions

Prohibited without explicit evidence/authority:

- direct `main` mutation for ordinary feature work;
- hidden source edits by validators;
- unrelated-file inclusion;
- test/acceptance weakening to obtain a pass;
- unverified deployment claims;
- treating Preview/staging evidence as Production evidence;
- claiming a different SHA's test result applies to current head without review;
- treating implementation self-check as independent validation.

## Templates

- CTO work contract: `docs/operations/templates/CTO_WORK_ORDER.md`
- Web Developer report: `docs/operations/templates/WEB_DEVELOPER_REPORT.md`
- Local Validation report: `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`
- CTO final review: `docs/operations/templates/CTO_FINAL_REVIEW.md`

Evidence requirements and workflow states are defined in:

- `docs/operations/EVIDENCE_REQUIREMENTS.md`
- `docs/operations/WORKFLOW_STATUS_MODEL.md`
