# Development Evidence Requirements

- Status: canonical
- Authority: Issue #148

## 1. Revision identity

Every implementation, validation, and final-review report records:

- repository and default branch;
- exact starting base SHA;
- target branch;
- exact reported/tested/reviewed head SHA;
- merge-base or ahead/behind relationship when relevant;
- clean/dirty worktree state, or that work was performed through branch-only GitHub writes.

Use full SHAs when available. Evidence for an older head is not automatically evidence for a newer head.

## 2. Scope evidence

Record:

- selected evidence stage;
- allowed paths;
- forbidden paths;
- exact changed-file list;
- reason for each changed file;
- diff statistics and compare/diff reference;
- explicit non-goals preserved;
- confirmation that unrelated files are absent.

A scope mismatch is a blocker until reviewed.

## 3. Implementation evidence

The Web Developer report includes:

- exact base/head and branch;
- changed behavior/contracts;
- automated commands and target revision;
- exit/status and pass/fail/skip counts;
- CI/check references when configured;
- self-check/browser/local evidence clearly labelled non-independent when run by the implementer;
- known defects, deferred items, environment limits, and remaining validation.

Do not report an unexecuted, unavailable, failed, or skipped check as passing.

## 4. Independent validation evidence

When the work contract requires independent validation, record:

- expected and actual tested head;
- validator identity/role relative to implementation;
- OS/runtime/browser/hardware/local-service environment;
- repository state before validation;
- whether source was modified;
- setup/build/run/test commands and exits;
- required journeys and actual results;
- desktop/mobile/reduced-motion/focus evidence when applicable;
- console, page, failed-request, overflow, asset, and external-request counts when applicable;
- artifacts such as screenshots/recordings/logs;
- reproducible failure evidence.

If the validator changes product source, the resulting run is not independent validation of the new revision.

## 5. Visual evidence

For visual/UI claims, prefer real rendered evidence at the exact tested revision.

Record as applicable:

- viewport dimensions;
- route/state;
- screenshot or video artifact;
- text readability/contrast issues;
- clipping and horizontal overflow;
- mobile hierarchy;
- keyboard/focus behavior;
- reduced-motion state;
- console/page/network failures.

A screenshot generated from the wrong project or unrelated deployment is not product evidence.

## 6. Runtime/provider evidence

For live or local runtime claims, distinguish:

- deterministic mock;
- source-equivalent local execution;
- exact-head local execution;
- live provider/API call;
- Preview/staging;
- Production.

Record provider/model/runtime identity, request/route evidence, timeout/retry/fallback boundaries, cost basis, and whether secrets were required. Never expose credentials.

## 7. Production evidence

Production evidence follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` and records the relevant subset of:

- resulting main/release SHA;
- deployment/version ID;
- project/Worker identity;
- root/source directory;
- hostname/TLS;
- critical HTTP/API behavior;
- browser journey;
- console/page/network failures;
- Access/authentication behavior;
- public-byte or commit metadata linkage when available;
- known-good recovery source/configuration.

HTTP 200 alone is not revision identity.

## 8. CTO final-review evidence

The final review records:

- exact reviewed head;
- current main/base relationship;
- actual changed files and scope verdict;
- acceptance criterion by criterion result;
- automated evidence sufficiency;
- independent validation requirement/status and exact-head match;
- security/privacy/regression considerations;
- owner-only decisions still required, if any;
- remaining limitations/conditions;
- final `READY`, `CONDITIONALLY_READY`, or `NOT_READY`.

Only the Web CTO assigns those final technical/review statuses.

## 9. Failure evidence

Good failure evidence separates observation from hypothesis and includes:

- expected result;
- actual result;
- exact action/command;
- exact tested SHA;
- exit/status;
- relevant error output;
- minimal reproduction;
- environment;
- source-modification status.

## 10. Evidence rejection conditions

Do not rely on these as sole completion evidence:

- test results without revision identity;
- another head's result without applicability review;
- “passed” statements without command/status evidence;
- implementer self-check presented as independent validation;
- hidden source edits during validation;
- report/diff mismatch;
- missing failed/skipped counts;
- wrong-project Preview/deployment;
- unverified Production claims;
- evidence containing secrets or private data.

## Templates

- `templates/WEB_DEVELOPER_REPORT.md`
- `templates/LOCAL_VALIDATION_REPORT.md`
- `templates/CTO_FINAL_REVIEW.md`
